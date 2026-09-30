from pathlib import Path

from pydantic import SecretStr, field_validator
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

    # GitHub OAuth app (US-1). The app's registered callback URL must equal
    # github_oauth_redirect_uri exactly. It points at the frontend callback page,
    # which relays code + state to POST /api/auth/github/callback, so a failed
    # sign-in is a 401 the page can show rather than a bare JSON error.
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None
    github_oauth_redirect_uri: str = "http://localhost:3000/auth/github/callback"
    github_oauth_scope: str = "read:user user:email"
    # Fernet key that encrypts OAuth access tokens at rest. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: SecretStr | None = None

    # Postgres holds users, workspaces and membership (US-41). The graph DB holds
    # nodes/edges/evidence; who may see a workspace is a relational question.
    database_url: str = "postgresql+psycopg://cortex:cortex@localhost:5432/cortex"
    session_cookie_name: str = "cortex_session"
    session_ttl_days: int = 30
    secure_cookies: bool = False

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

    @property
    def github_oauth_configured(self) -> bool:
        return bool(
            self.github_client_id
            and self.github_client_secret
            and self.token_encryption_key
        )


settings = Settings()
