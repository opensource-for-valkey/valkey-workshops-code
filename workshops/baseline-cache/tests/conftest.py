import os
from uuid import uuid4

from dotenv import load_dotenv
import pytest
from sqlalchemy import create_engine, text

from core import get_cache_client


@pytest.fixture
def cache(monkeypatch):
    load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))
    if not (os.getenv("VALKEY_PASSWORD") or os.getenv("CACHE_PASSWORD")):
        pytest.skip("Configure an authenticated workshop Valkey instance")
    monkeypatch.setenv("CACHE_KEY_PREFIX", f"baseline:test:{uuid4().hex}:")
    instance = get_cache_client()
    assert instance.client.ping() == b"PONG"
    yield instance
    instance.flush_all()
    instance.close()


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE airport (airport_id INTEGER PRIMARY KEY, iata TEXT)"))
        connection.execute(text("INSERT INTO airport VALUES (1, 'LHR'), (2, 'JFK')"))
        connection.execute(text("CREATE TABLE airline (airline_id INTEGER PRIMARY KEY, airlinename TEXT)"))
        connection.execute(text("INSERT INTO airline VALUES (1, 'Workshop Air')"))
        connection.execute(text("""
            CREATE TABLE flight (
                flight_id INTEGER PRIMARY KEY, flightno TEXT,
                "from" INTEGER, "to" INTEGER,
                departure DATETIME, arrival DATETIME,
                airline_id INTEGER, airplane_id INTEGER
            )
        """))
        connection.execute(text("""
            INSERT INTO flight VALUES (
                1, 'WS001', 1, 2,
                '2026-11-23 10:00:00', '2026-11-23 12:00:00', 1, 1
            )
        """))
        connection.execute(text("""
            CREATE TABLE flight_log (
                log_date DATETIME, "user" TEXT, flight_id INTEGER,
                flightno_old TEXT, flightno_new TEXT,
                from_old INTEGER, from_new INTEGER, to_old INTEGER, to_new INTEGER,
                departure_old DATETIME, departure_new DATETIME,
                arrival_old DATETIME, arrival_new DATETIME,
                airplane_id_old INTEGER, airplane_id_new INTEGER,
                airline_id_old INTEGER, airline_id_new INTEGER, comment TEXT
            )
        """))
    yield engine
    engine.dispose()
