"""The FAQ lab must find its bundled corpus without any environment override."""

from pathlib import Path

FAQ_PROJECT = Path(__file__).resolve().parents[1] / "semantic-faq"


def test_default_data_dir_is_the_bundled_corpus(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(FAQ_PROJECT))
    monkeypatch.delenv("SEMANTIC_FAQ_DATA_DIR", raising=False)
    # Point dotenv at an empty file so a developer's private .env cannot mask the default.
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    monkeypatch.setenv("WORKSHOP_ENV_FILE", str(empty_env))
    from semantic_cache.settings import Settings

    settings = Settings.from_environment()

    assert settings.data_dir == FAQ_PROJECT / "data"
    assert sorted(settings.data_dir.glob("*-faq.md"))
    settings.validate()
