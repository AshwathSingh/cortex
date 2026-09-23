from pathlib import Path

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


settings = Settings()
