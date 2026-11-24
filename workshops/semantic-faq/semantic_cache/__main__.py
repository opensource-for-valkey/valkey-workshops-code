"""Run the FAQ demonstration on loopback using environment configuration."""

import os

from dotenv import load_dotenv
from rich.console import Console


def main() -> None:
    load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"), override=False)
    import uvicorn

    host = os.environ.get("SEMANTIC_FAQ_API_HOST", "127.0.0.1")
    port = int(os.environ.get("SEMANTIC_FAQ_API_PORT", "8000"))
    Console().print(f"[bold]FAQ semantic cache[/bold] · http://{host}:{port}")
    uvicorn.run("semantic_cache.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
