"""Create private local configuration without printing any credentials."""

from pathlib import Path
import os
import secrets

from dotenv import dotenv_values, set_key
from rich.console import Console


def provisioned_credentials(destination: Path) -> dict:
    """Find the private service settings without importing them into the shell."""
    explicit = os.environ.get("WORKSHOP_CREDENTIALS_FILE")
    if explicit:
        if not Path(explicit).is_file():
            raise FileNotFoundError("WORKSHOP_CREDENTIALS_FILE does not exist")
        return dotenv_values(explicit)
    candidates = [parent / ".valkey.env" for parent in destination.resolve().parents]
    candidates += [Path.home() / "workshop/.valkey.env", Path.home() / "workshop/valkey/.valkey.env"]
    for candidate in candidates:
        if candidate.is_file():
            return dotenv_values(candidate)
    return {}


def main() -> None:
    destination = Path(os.environ.get("WORKSHOP_ENV_FILE", ".env"))
    if not destination.exists():
        destination.write_text(Path(".env.example").read_text())
    destination.chmod(0o600)
    settings = dotenv_values(destination)
    provisioned = provisioned_credentials(destination)
    if not settings.get("VALKEY_PASSWORD"):
        password = os.environ.get("VALKEY_PASSWORD") or provisioned.get("VALKEY_PASSWORD") or secrets.token_urlsafe(32)
        set_key(destination, "VALKEY_PASSWORD", password)
    if not settings.get("SECRET_KEY"):
        set_key(destination, "SECRET_KEY", secrets.token_urlsafe(32))
    if not settings.get("VECTOR_PASSWORD"):
        set_key(destination, "VECTOR_PASSWORD", os.environ.get("VECTOR_PASSWORD") or dotenv_values(destination)["VALKEY_PASSWORD"])
    if not settings.get("DB_PASSWORD"):
        for parent in destination.resolve().parents:
            password_file = parent / ".db_password"
            if password_file.is_file():
                set_key(destination, "DB_PASSWORD", password_file.read_text().strip())
                break
    Console().print(f"[green]Private configuration ready:[/green] {destination}")
    Console().print("Match VALKEY_PASSWORD, VECTOR_PASSWORD and DB_PASSWORD to the provisioned services.")


if __name__ == "__main__":
    main()
