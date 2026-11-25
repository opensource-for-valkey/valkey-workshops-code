"""Live, best-effort events between separate processes, with measured latency."""

import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from common import console, key, timed
from valkey_client import ValkeyClientManager


def event_age_ms(event, received_at):
    """Wall-clock event age needs aligned clocks; manual events have no timestamp."""
    try:
        occurred_at = datetime.fromisoformat(event.get("occurred_at", ""))
    except (TypeError, ValueError):
        return None
    if occurred_at.tzinfo is None:
        return None
    return (received_at - occurred_at).total_seconds() * 1000


def publish() -> None:
    with ValkeyClientManager() as client:
        event = {
            "event_id": str(uuid4()),
            "type": "score.updated",
            "player": "Ada",
            "score": 125,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        recipients, publish_ms = timed(
            client.publish, json.dumps(event), key("events", "scores")
        )
    console.print_json(data=event)
    console.print(
        f"Publishing node reported {recipients} subscriptions; "
        f"Valkey PUBLISH response: {publish_ms:.3f} ms; "
        "this is not a processing acknowledgement."
    )


def subscribe() -> None:
    channel = key("events", "scores")
    # GLIDE establishes the configured subscriptions during client creation.
    setup_started = time.perf_counter_ns()
    with ValkeyClientManager(channels={channel}) as subscriber:
        setup_ms = (time.perf_counter_ns() - setup_started) / 1_000_000
        console.print(
            f"READY: subscribed to {channel}; connection/subscription setup: "
            f"{setup_ms:.3f} ms. Press Ctrl+C to stop."
        )
        while True:
            # Native GLIDE dequeues a local buffer; Sentinel calls may also rediscover the primary.
            message, dequeue_ms = timed(subscriber.try_get_pubsub_message)
            if message is not None:
                received_at = datetime.now(timezone.utc)
                event = json.loads(message.message)
                age = event_age_ms(event, received_at)
                age_label = "unavailable" if age is None else f"{age:.3f} ms"
                console.print(
                    f"Received {event['event_id']}: {event['player']} scored {event['score']}; "
                    f"GLIDE dequeue call: {dequeue_ms:.3f} ms; "
                    f"event age (clock-dependent): {age_label}"
                )
            else:
                # Quiet-channel polling adds up to this interval to observed event age.
                time.sleep(0.02)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("subscribe", "publish"))
    args = parser.parse_args()
    try:
        if args.action == "subscribe":
            subscribe()
        else:
            publish()
    except KeyboardInterrupt:
        console.print("\nSubscriber stopped. Events published while disconnected will not be replayed.")


if __name__ == "__main__":
    main()
