import os
from pathlib import Path
import secrets
import stat

from dotenv import dotenv_values, set_key

import setup_env


def test_provisioned_secret_and_db_password_are_reused_without_output(tmp_path, monkeypatch, capsys):
    project = tmp_path / "workshop/baseline-cache"
    project.mkdir(parents=True)
    password = secrets.token_urlsafe(32)
    db_password = secrets.token_urlsafe(32)
    provisioned = project.parent / ".valkey.env"
    provisioned.write_text(f"VALKEY_PASSWORD={password}\n")
    (project.parent / ".db_password").write_text(db_password)
    monkeypatch.chdir(project)
    monkeypatch.delenv("WORKSHOP_ENV_FILE", raising=False)
    monkeypatch.delenv("WORKSHOP_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)
    monkeypatch.delenv("VECTOR_PASSWORD", raising=False)
    example = Path(__file__).resolve().parents[1] / ".env.example"
    (project / ".env.example").write_text(example.read_text())
    setup_env.main()
    values = dotenv_values(project / ".env")
    assert values["VALKEY_PASSWORD"] == password
    assert values["VECTOR_PASSWORD"] == password
    assert values["DB_PASSWORD"] == db_password
    assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
    assert password not in capsys.readouterr().out
    saved = secrets.token_urlsafe(32)
    set_key(project / ".env", "VALKEY_PASSWORD", saved)
    monkeypatch.setenv("VALKEY_PASSWORD", secrets.token_urlsafe(32))
    setup_env.main()
    assert dotenv_values(project / ".env")["VALKEY_PASSWORD"] == saved


def test_exported_secret_precedes_explicit_provisioned_file(tmp_path, monkeypatch):
    provisioned = tmp_path / "private.env"
    provisioned.write_text(f"VALKEY_PASSWORD={secrets.token_urlsafe(32)}\n")
    destination = tmp_path / ".env"
    destination.write_text("VALKEY_PASSWORD=\nSECRET_KEY=\nVECTOR_PASSWORD=\n")
    exported = secrets.token_urlsafe(32)
    monkeypatch.setenv("WORKSHOP_ENV_FILE", str(destination))
    monkeypatch.setenv("WORKSHOP_CREDENTIALS_FILE", str(provisioned))
    monkeypatch.setenv("VALKEY_PASSWORD", exported)
    setup_env.main()
    assert dotenv_values(destination)["VALKEY_PASSWORD"] == exported
