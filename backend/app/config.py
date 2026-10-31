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
    # Fernet key that encrypts OAuth tokens at rest. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Validated at startup (app.security.validate_encryption_keys), not here: a
    # pydantic error would echo the raw key into the log.
    token_encryption_key: SecretStr | None = None
    # Comma-separated keys that may still decrypt but never encrypt. Put the old
    # key here when rotating, run scripts.rotate_token_key, then remove it.
    token_encryption_previous_keys: SecretStr | None = None
    # Per client IP, per endpoint, on the public /api/auth/github/* routes.
    oauth_rate_limit_per_minute: int = 20

    # Slack app (US-08, T-8.2). A workspace member with sources.write installs
    # Cortex into their Slack team; the exchange returns a bot token scoped to
    # that team, which is stored encrypted per workspace. The registered
    # redirect URL must equal slack_oauth_redirect_uri exactly.
    slack_client_id: str | None = None
    slack_client_secret: SecretStr | None = None
    slack_oauth_redirect_uri: str = "http://localhost:3000/sources/slack/callback"
    # Bot scopes. The history pair is what lets Cortex read messages at all; the
    # read pair lists the channels to choose from; users:read resolves authors to
    # names instead of raw Uxxxx ids.
    slack_oauth_scope: str = (
        "channels:read,channels:history,groups:read,groups:history,users:read"
    )

    # Discord app (US-08, T-8.3). Unlike Slack and GitHub this is not a user
    # token flow: Discord's HTTP API will not return channel history for a user
    # token, so reads use the application's own bot token and the install flow
    # exists only to add that bot to a guild and learn which guild it is.
    discord_client_id: str | None = None
    discord_client_secret: SecretStr | None = None
    discord_oauth_redirect_uri: str = "http://localhost:3000/sources/discord/callback"
    discord_bot_token: SecretStr | None = None
    # View Channels (1024) + Read Message History (65536). Requested in the
    # invite URL so an owner can see exactly what the bot may do before adding it.
    discord_bot_permissions: str = "66560"

    # Postgres holds users, workspaces and membership (US-41). The graph DB holds
    # nodes/edges/evidence; who may see a workspace is a relational question.
    database_url: str = "postgresql+psycopg://cortex:cortex@localhost:5432/cortex"
    session_cookie_name: str = "cortex_session"
    session_ttl_days: int = 30
    secure_cookies: bool = False

    @field_validator(
        "github_client_secret",
        "token_encryption_key",
        "token_encryption_previous_keys",
        "slack_client_secret",
        "discord_client_secret",
        "discord_bot_token",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_unset(cls, v):
        # `.env.example` ships `TOKEN_ENCRYPTION_KEY=`; treat that as not configured.
        return None if isinstance(v, str) and not v.strip() else v

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
    def token_encryption_previous_key_list(self) -> list[str]:
        if self.token_encryption_previous_keys is None:
            return []
        raw = self.token_encryption_previous_keys.get_secret_value()
        return [key.strip() for key in raw.split(",") if key.strip()]

    @property
    def github_oauth_configured(self) -> bool:
        return bool(
            self.github_client_id
            and self.github_client_secret
            and self.token_encryption_key
        )

    @property
    def slack_configured(self) -> bool:
        # token_encryption_key included because the exchange returns a bot token
        # there would be nowhere safe to put: the column encrypts on write.
        return bool(
            self.slack_client_id
            and self.slack_client_secret
            and self.token_encryption_key
        )

    @property
    def discord_configured(self) -> bool:
        # No encryption key needed: the bot token lives in config, not in a row.
        return bool(
            self.discord_client_id
            and self.discord_client_secret
            and self.discord_bot_token
        )


settings = Settings()
