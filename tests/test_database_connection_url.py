from sqlalchemy.engine import make_url

from database.db_connection import get_database_url


def test_component_credentials_round_trip_with_reserved_characters(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "nija_test")
    monkeypatch.setenv("POSTGRES_USER", "role@example")
    sample = "fake@credential:with/?#% characters"
    monkeypatch.setenv("POSTGRES_PASSWORD", sample)

    parsed = make_url(get_database_url())

    assert (parsed.username, parsed.password) == ("role@example", sample)
    assert (parsed.host, parsed.port, parsed.database) == ("localhost", 5433, "nija_test")
