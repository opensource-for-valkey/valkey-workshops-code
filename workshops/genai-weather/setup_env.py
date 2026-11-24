"""Create private workshop settings without printing credentials."""

from pathlib import Path
import os
import secrets

from dotenv import dotenv_values, set_key
from rich.console import Console


def provisioned_password(destination: Path) -> str | None:
    explicit = os.environ.get("WORKSHOP_CREDENTIALS_FILE")
    candidates = [Path(explicit).expanduser()] if explicit else []
    parent = destination.resolve().parent
    candidates.extend(folder / ".valkey.env" for folder in (parent, *parent.parents))
    candidates.extend(
        [
            Path.home() / "workshop/.valkey.env",
            Path.home() / "workshop/valkey/.valkey.env",
        ]
    )
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file():
            password = dotenv_values(candidate).get("VALKEY_PASSWORD")
            if password:
                return password
    return None


def main() -> None:
    destination = Path(os.environ.get("WORKSHOP_ENV_FILE", ".env"))
    if not destination.exists():
        destination.write_text(Path(".env.example").read_text())
    destination.chmod(0o600)
    if not dotenv_values(destination).get("VALKEY_PASSWORD"):
        password = (
            os.environ.get("VALKEY_PASSWORD")
            or provisioned_password(destination)
            or secrets.token_urlsafe(32)
        )
        set_key(destination, "VALKEY_PASSWORD", password)
    Console().print(f"[green]Private configuration ready:[/green] {destination}")


if __name__ == "__main__":
    main()
