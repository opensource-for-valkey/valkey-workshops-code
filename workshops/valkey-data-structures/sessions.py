"""Share a session Hash between application instances without reviving expiry."""

import time

from glide_sync import Script
from rich.table import Table

from common import console, key, new_batch, text, timed
from valkey_client import ValkeyClientManager


UPDATE_SESSION = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return nil
end
redis.call('HSET', KEYS[1], 'theme', ARGV[1])
return redis.call('HINCRBY', KEYS[1], 'visits', 1)
"""
UPDATE_SCRIPT = Script(UPDATE_SESSION)


def session_key(session_id):
    return key("session", session_id)


def create_session(client, session_id, user_id, ttl=120):
    # MULTI/EXEC prevents a successfully committed session from lacking its TTL.
    transaction = new_batch(client, is_atomic=True)
    transaction.hset(
        session_key(session_id),
        {"user_id": user_id, "theme": "light", "visits": "0"},
    )
    transaction.expire(session_key(session_id), ttl)
    client.exec(transaction, raise_on_error=True)


def read_session(client, session_id):
    return {text(field): text(value)
            for field, value in client.hgetall(session_key(session_id)).items()}


def update_session(client, session_id, theme):
    # The existence check and mutation are atomic, including against expiry.
    return client.invoke_script(
        UPDATE_SCRIPT, keys=[session_key(session_id)], args=[theme]
    )


def demonstrate(app_a, app_b):
    session_id = "demo-session"
    expired_id = "expiry-check"
    removed, elapsed_ms = timed(
        app_a.delete, [session_key(session_id), session_key(expired_id)]
    )
    console.print(f"Session reset: {removed} keys; Valkey DEL latency={elapsed_ms:.3f} ms")
    _, elapsed_ms = timed(create_session, app_a, session_id, "u42")
    console.print(f"Session creation: committed; Valkey transaction latency={elapsed_ms:.3f} ms")
    initial, elapsed_ms = timed(read_session, app_b, session_id)
    assert initial["user_id"] == "u42"
    console.print(f"Application B first read: {initial}; Valkey HGETALL latency={elapsed_ms:.3f} ms")
    visits, elapsed_ms = timed(update_session, app_a, session_id, "dark")
    assert visits == 1
    console.print(f"Application A update: visits={visits}; Valkey script latency={elapsed_ms:.3f} ms")
    visits, elapsed_ms = timed(update_session, app_b, session_id, "blue")
    assert visits == 2
    console.print(f"Application B update: visits={visits}; Valkey script latency={elapsed_ms:.3f} ms")
    shared, read_ms = timed(read_session, app_b, session_id)
    assert shared == {"user_id": "u42", "theme": "blue", "visits": "2"}
    table = Table(
        title="Shared session · two GLIDE clients",
        caption=f"Valkey HGETALL response latency={read_ms:.3f} ms",
    )
    table.add_column("Field")
    table.add_column("Application B sees")
    for field, value in shared.items():
        table.add_row(field, value)
    console.print(table)
    ttl, elapsed_ms = timed(app_a.ttl, session_key(session_id))
    console.print(f"TTL after field updates: {ttl} s; Valkey TTL latency={elapsed_ms:.3f} ms")

    _, elapsed_ms = timed(create_session, app_a, expired_id, "u42", ttl=1)
    console.print(f"Expiry-test creation: committed; Valkey transaction latency={elapsed_ms:.3f} ms")
    time.sleep(1.1)  # Waiting for expiry is outside the response measurements.
    expired, read_ms = timed(read_session, app_b, expired_id)
    refused, update_ms = timed(update_session, app_b, expired_id, "dark")
    exists, exists_ms = timed(app_a.exists, [session_key(expired_id)])
    assert expired == {} and refused is None and exists == 0
    console.print("Expired session: missing; update refused; key stays absent")
    console.print(
        f"Valkey expiry-check latencies: HGETALL={read_ms:.3f} ms; "
        f"script={update_ms:.3f} ms; EXISTS={exists_ms:.3f} ms"
    )
    console.print(f"Inspect shared session: {session_key(session_id)}")


def main():
    with ValkeyClientManager() as app_a, ValkeyClientManager() as app_b:
        demonstrate(app_a, app_b)


if __name__ == "__main__":
    main()
