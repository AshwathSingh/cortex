"""Apply every relational schema migration.

Usage: python -m scripts.init_postgres_schema

Kept as a convenience alias for the original US-41 command. Alembic remains the
single source of truth for schema changes.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(backend_dir / "alembic.ini")), "head")
    print("Postgres migrations applied.")


if __name__ == "__main__":
    main()
