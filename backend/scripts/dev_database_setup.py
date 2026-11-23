"""Wait for configured databases, then apply both schemas without deleting data."""

import os
import time
from pathlib import Path
from dotenv import load_dotenv


def main():
    load_dotenv(
        os.environ.get("CORTEX_ENV_FILE", Path(__file__).resolve().parents[2] / ".env")
    )
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from neo4j.exceptions import DriverError, Neo4jError
    from app.db.postgres import get_engine
    from app.db.neo4j_driver import get_driver
    from scripts.init_postgres_schema import main as postgres_schema
    from scripts.init_graph_schema import main as graph_schema

    deadline = time.monotonic() + 90
    while True:
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
            get_driver().verify_connectivity()
            break
        except (SQLAlchemyError, DriverError, Neo4jError, OSError):
            if time.monotonic() >= deadline:
                raise SystemExit(
                    "Databases are not ready. Check Docker and .env credentials; existing volumes retain their original credentials. No data was reset."
                )
            print("Waiting for PostgreSQL and Neo4j…", flush=True)
            time.sleep(2)
    postgres_schema()
    graph_schema()
    print("PostgreSQL and Neo4j are ready; schemas are current.")


if __name__ == "__main__":
    main()
