from app.config import Settings


def test_legacy_postgres_url_uses_psycopg3_driver():
    settings = Settings(database_url="postgresql://user:pass@localhost:5432/cortex")

    assert settings.database_url.startswith("postgresql+psycopg://")
