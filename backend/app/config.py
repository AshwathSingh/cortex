from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env, so settings load the same regardless of the working directory.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cortexgraph"

    # Optional server-side token; raises the GitHub rate limit. Never accepted from
    # requests or returned in responses. Replaced by per-user OAuth tokens (US-1).
    github_token: str | None = None

    # Postgres holds users, workspaces and membership (US-41). The graph DB holds
    # nodes/edges/evidence; who may see a workspace is a relational question.
    database_url: str = "postgresql+psycopg://cortex:cortex@localhost:5432/cortex"

    @field_validator("database_url")
    @classmethod
    def _pin_psycopg_driver(cls, v: str) -> str:
        """Force the psycopg (v3) driver onto a bare ``postgresql://`` URL.

        ``.env.example`` ships ``DATABASE_URL=postgresql://...``, and SQLAlchemy
        reads a driver-less URL as psycopg2, which this project does not install.
        Rewriting here means nobody has to edit their existing .env.
        """
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v


settings = Settings()
