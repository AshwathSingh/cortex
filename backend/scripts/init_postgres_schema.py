"""Apply every relational schema migration.

Usage: python -m scripts.init_postgres_schema

Kept as a convenience alias for the original US-41 command. Alembic remains the
single source of truth for schema changes.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.db.postgres import dispose_engine, get_engine


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    try:
        table_names = set(inspect(get_engine()).get_table_names())
        if "users" in table_names and "alembic_version" not in table_names:
            raise SystemExit(
                "Legacy Postgres schema detected. Back up any needed local data, "
                "reset the public schema using the command in backend/README.md, "
                "then rerun this command."
            )

        command.upgrade(Config(str(backend_dir / "alembic.ini")), "head")
        print("Postgres migrations applied.")
    finally:
        dispose_engine()


if __name__ == "__main__":
    main()
