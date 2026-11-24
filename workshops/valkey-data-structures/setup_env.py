"""Generate local configuration without printing or replacing credentials."""

import os
import secrets
from pathlib import Path

from rich.console import Console


def main() -> None:
    selected = os.environ.get("VALKEY_ENV_FILE") or os.environ.get("WORKSHOP_ENV_FILE")
    path = Path(selected).expanduser() if selected else Path(__file__).with_name(".env")
    if path.exists():
        Console().print(f"Using existing configuration: {path.name}")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("COMPOSE_PROJECT_NAME=valkey-data-structures-lab\n")
        output.write("VALKEY_MODE=standalone\nVALKEY_NODES=\n")
        output.write("VALKEY_HOST=127.0.0.1\nVALKEY_PORT=6381\n")
        output.write("VALKEY_ADMIN_PORT=8082\nVALKEY_USERNAME=default\n")
        output.write("VALKEY_DATABASE=0\nVALKEY_REQUEST_TIMEOUT_MS=5000\n")
        output.write("VALKEY_CONNECTION_TIMEOUT_MS=3000\n")
        output.write("VALKEY_CLIENT_NAME=valkey-data-structures-workshop\n")
        output.write("VALKEY_TLS=false\nVALKEY_TLS_CA_CERT=\n")
        output.write("VALKEY_TLS_CLIENT_CERT=\nVALKEY_TLS_CLIENT_KEY=\n")
        output.write("VALKEY_KEY_PREFIX=ds\n")
        output.write(f"VALKEY_PASSWORD={secrets.token_hex(24)}\n")
    Console().print(f"Created {path.name} with private permissions and a random password.")


if __name__ == "__main__":
    main()
