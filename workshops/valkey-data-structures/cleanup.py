"""Remove the workshop's prefixed keys after all lab processes have stopped."""

from common import LatencyTimer, console, key, scan_keys
from valkey_client import ValkeyClientManager


def main():
    removed = 0
    with ValkeyClientManager() as client:
        with LatencyTimer() as timer:
            batch = []
            for name in scan_keys(client, f"{key()}:*"):
                batch.append(name)
                if len(batch) == 100:
                    removed += client.unlink(batch)
                    batch.clear()
            if batch:
                removed += client.unlink(batch)
    console.print(
        f"Removed {removed} keys from {key()}; SCAN + UNLINK latency: {timer.elapsed_ms:.3f} ms"
    )


if __name__ == "__main__":
    main()
