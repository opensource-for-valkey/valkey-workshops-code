"""Regression tests for the public RDBMS connection factory."""

from sqlalchemy.dialects import mysql, postgresql

from core.rdbms import RDBMSConnection, quote_identifier


def test_reserved_characters_remain_in_database_credentials():
    connection = RDBMSConnection(
        db_type="mysql",
        host="db.example",
        port="3306",
        user="workshop@example.com",
        password="p@ss:/word",
        database="flights",
    )

    url = connection.get_engine().url

    assert url.username == "workshop@example.com"
    assert url.password == "p@ss:/word"
    assert url.host == "db.example"
    assert url.port == 3306
    assert url.database == "flights"


def test_reserved_identifiers_are_quoted_for_each_database_dialect():
    class FakeEngine:
        def __init__(self, dialect):
            self.dialect = dialect

    assert quote_identifier(FakeEngine(mysql.dialect()), "from") == "`from`"
    assert quote_identifier(FakeEngine(postgresql.dialect()), "from") == '"from"'
