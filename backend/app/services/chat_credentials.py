"""T-8.2: storing and reading a workspace's chat-provider connection.

Everything above this module -- the ingestion endpoints, the channel listing --
asks one question: "give me a usable token for this workspace's Slack/Discord".
Where that token comes from differs by provider and nothing else should have to
know it. Slack's lives encrypted in the row the install wrote; Discord's is the
application-wide bot token in config, and the row only records which guild the
bot was added to.

A credential encrypted under a key that is no longer configured is treated the
same way ``app.services.github_credentials`` treats one: deleted, with
``SourceCredentialMissing`` raised, so the caller sends the user back through
the install flow instead of failing with a 500. Re-authorising is always the
recovery path.
"""

import uuid
from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SourceCredential
from app.sources.base import KIND_DISCORD, KIND_SLACK
from app.sources.chat_oauth import ChatInstall


class SourceCredentialMissing(Exception):
    """This workspace has no usable connection to the provider. The fix is to
    authorise it again, never a retry."""


@dataclass(frozen=True)
class ChatCredential:
    """A connection resolved to something an adapter can use."""

    kind: str
    external_ref: str
    display_name: str
    token: str

    def __repr__(self) -> str:
        return (
            f"ChatCredential(kind={self.kind!r}, "
            f"external_ref={self.external_ref!r})"
        )


def save_chat_credential(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    kind: str,
    install: ChatInstall,
    user_id: uuid.UUID | None,
) -> SourceCredential:
    """Record (or replace) this workspace's connection. Does not commit.

    Replaces rather than updates: re-authorising may have landed on a different
    team or guild, and carrying over the old row's ``external_ref`` would leave
    the ``data_sources`` key pointing at a source nobody authorised. The delete
    is unconditional for the same reason a fresh GitHub sign-in never reads the
    old row -- an unreadable ciphertext must not be able to block reconnecting.
    """
    session.execute(
        delete(SourceCredential).where(
            SourceCredential.workspace_id == workspace_id,
            SourceCredential.kind == kind,
        )
    )
    credential = SourceCredential(
        workspace_id=workspace_id,
        kind=kind,
        external_ref=install.external_ref,
        display_name=install.display_name,
        access_token=install.access_token,
        scope=install.scope,
        installed_by=user_id,
    )
    session.add(credential)
    return credential


def _discard(session: Session, workspace_id: uuid.UUID, kind: str) -> None:
    session.rollback()
    session.execute(
        delete(SourceCredential).where(
            SourceCredential.workspace_id == workspace_id,
            SourceCredential.kind == kind,
        )
    )
    session.commit()


def get_chat_credential(
    session: Session, *, workspace_id: uuid.UUID, kind: str
) -> ChatCredential:
    """This workspace's connection to ``kind``, with a token ready to use.

    Raises ``SourceCredentialMissing`` when the workspace has not connected the
    provider, when the stored token can no longer be decrypted, or -- for
    Discord -- when the server has no bot token configured, since the row alone
    cannot read anything.
    """
    try:
        credential = session.scalar(
            select(SourceCredential).where(
                SourceCredential.workspace_id == workspace_id,
                SourceCredential.kind == kind,
            )
        )
    except InvalidToken:
        # Encrypted under a key that is no longer configured.
        _discard(session, workspace_id, kind)
        raise SourceCredentialMissing(kind) from None

    if credential is None:
        raise SourceCredentialMissing(kind)

    token = _resolve_token(credential)
    if token is None:
        raise SourceCredentialMissing(kind)

    return ChatCredential(
        kind=credential.kind,
        external_ref=credential.external_ref,
        display_name=credential.display_name,
        token=token,
    )


def _resolve_token(credential: SourceCredential) -> str | None:
    if credential.kind == KIND_DISCORD:
        # One application-wide secret, so it is read fresh on every call and
        # rotating it needs no database write.
        bot_token = settings.discord_bot_token
        return bot_token.get_secret_value() if bot_token else None
    return credential.access_token


def list_chat_connections(
    session: Session, workspace_id: uuid.UUID
) -> dict[str, SourceCredential]:
    """The workspace's connections keyed by kind, for the Sources page.

    Returns the rows themselves, not resolved tokens: the UI needs to say
    *that* Slack is connected and what it is called, and must never be handed
    the credential to say it with.
    """
    rows = session.scalars(
        select(SourceCredential).where(
            SourceCredential.workspace_id == workspace_id,
            SourceCredential.kind.in_((KIND_SLACK, KIND_DISCORD)),
        )
    ).all()
    return {row.kind: row for row in rows}


def delete_chat_credential(
    session: Session, *, workspace_id: uuid.UUID, kind: str
) -> bool:
    """Disconnect the provider. Does not commit. True if a row was removed.

    The ``data_sources`` row and the graph nodes are left alone on purpose:
    disconnecting stops future syncs, it does not retract what was already
    ingested and linked.
    """
    result = session.execute(
        delete(SourceCredential).where(
            SourceCredential.workspace_id == workspace_id,
            SourceCredential.kind == kind,
        )
    )
    return bool(result.rowcount)
