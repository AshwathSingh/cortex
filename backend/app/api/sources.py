"""T-8.2: connecting and disconnecting a workspace's chat providers.

    GET    /api/sources/{kind}/install?workspace_id=...   -> 302 to the provider
    POST   /api/sources/{kind}/callback  {code, state}    -> stores the credential
    GET    /api/workspaces/{id}/connections               -> what is connected
    GET    /api/workspaces/{id}/connections/{kind}/channels -> channels to pick
    DELETE /api/workspaces/{id}/connections/{kind}        -> disconnect

``kind`` is "slack" or "discord". The flows differ in what they authorise -- a
team bot token versus a bot joining a guild -- but the shape is identical, so
the state handling, the permission checks and the single-use transaction live
here once.

Three things are checked on the way in, in this order: the caller is signed in,
they hold ``sources.write`` on the workspace they named, and the provider is
configured on this server. The permission is re-checked in the callback rather
than trusted from the install step, so a role revoked while the user was away at
Slack takes effect before anything is stored.

The ``state`` is server-side (hashed, single-use, ten minutes) *and* bound to
the browser by a cookie, the same pair ``app.api.auth`` uses for sign-in: the
row says which workspace and provider a callback is for, and the cookie proves
the callback reached the browser that started it.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.api.rate_limit import RateLimiter
from app.config import settings
from app.models import SourceInstallTransaction
from app.permissions import Permission
from app.security import hash_session_token
from app.services.chat_credentials import (
    SourceCredentialMissing,
    delete_chat_credential,
    get_chat_credential,
    list_chat_connections,
    save_chat_credential,
)
from app.sources.base import (
    KIND_DISCORD,
    KIND_SLACK,
    SourceError,
    SourceNotFound,
    SourceRateLimited,
    SourceUnauthorized,
)
from app.sources.discord import DiscordClient
from app.sources.slack import SlackClient
from app.sources.chat_oauth import (
    ChatInstallError,
    DiscordOAuthClient,
    SlackOAuthClient,
    discord_authorize_url,
    slack_authorize_url,
)

router = APIRouter(tags=["sources"])

ChatKind = Literal["slack", "discord"]

INSTALL_STATE_COOKIE = "cortex_source_install_state"
INSTALL_STATE_COOKIE_PATH = "/api/sources"
INSTALL_STATE_TTL_SECONDS = 10 * 60

# Separate buckets, so a burst of starts cannot lock someone out of finishing.
install_limiter = RateLimiter(settings.oauth_rate_limit_per_minute)
callback_limiter = RateLimiter(settings.oauth_rate_limit_per_minute)


class InstallCallbackRequest(BaseModel):
    code: str
    state: str


class ChannelOption(BaseModel):
    """One channel a member can choose to ingest (US-08 AC1/AC2)."""

    id: str
    name: str


class ConnectionResponse(BaseModel):
    """A connected provider as the UI sees it. No token, ever."""

    kind: str
    external_ref: str
    display_name: str
    installed_by_name: str | None = None
    #: Which workspace this belongs to. The provider redirects the browser to a
    #: callback page that knows only ``state``, so this is how that page finds
    #: its way back to the workspace the member started from.
    workspace_id: uuid.UUID


def _require_configured(kind: str) -> None:
    configured = (
        settings.slack_configured if kind == KIND_SLACK else settings.discord_configured
    )
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{kind.title()} is not configured on this server",
        )


def build_oauth_client(kind: str) -> SlackOAuthClient | DiscordOAuthClient:
    """The exchange client for ``kind``. The caller closes it."""
    if kind == KIND_SLACK:
        return SlackOAuthClient(
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret.get_secret_value(),
            redirect_uri=settings.slack_oauth_redirect_uri,
        )
    return DiscordOAuthClient(
        client_id=settings.discord_client_id,
        client_secret=settings.discord_client_secret.get_secret_value(),
        redirect_uri=settings.discord_oauth_redirect_uri,
    )


def get_oauth_client_builder():
    """Injectable so tests can supply a client with a mock transport."""
    return build_oauth_client


def _install_failed() -> HTTPException:
    # One message for every rejection, so the response does not say which check
    # failed -- the same reasoning as GitHub sign-in.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Connecting the source failed. Please try again.",
    )


@router.get(
    "/api/sources/{kind}/install", dependencies=[Depends(install_limiter)]
)
def start_install(
    kind: ChatKind,
    user: CurrentUser,
    session: DbSession,
    workspace_id: uuid.UUID = Query(...),
) -> RedirectResponse:
    """Begin connecting ``kind`` to ``workspace_id``."""
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.SOURCES_WRITE
    )
    _require_configured(kind)

    now = datetime.now(timezone.utc)
    state = secrets.token_urlsafe(32)

    # Abandoned installs would otherwise pile up; the rate limit bounds how many
    # one client can create between sweeps.
    session.execute(
        delete(SourceInstallTransaction).where(
            SourceInstallTransaction.expires_at <= now
        )
    )
    session.add(
        SourceInstallTransaction(
            state_hash=hash_session_token(state),
            workspace_id=workspace_id,
            kind=kind,
            user_id=user.id,
            expires_at=now + timedelta(seconds=INSTALL_STATE_TTL_SECONDS),
        )
    )
    session.commit()

    if kind == KIND_SLACK:
        target = slack_authorize_url(
            client_id=settings.slack_client_id,
            redirect_uri=settings.slack_oauth_redirect_uri,
            scope=settings.slack_oauth_scope,
            state=state,
        )
    else:
        target = discord_authorize_url(
            client_id=settings.discord_client_id,
            redirect_uri=settings.discord_oauth_redirect_uri,
            permissions=settings.discord_bot_permissions,
            state=state,
        )

    response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=INSTALL_STATE_COOKIE,
        value=state,
        max_age=INSTALL_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        # Lax still sends the cookie on the same-origin POST from the callback page.
        samesite="lax",
        path=INSTALL_STATE_COOKIE_PATH,
    )
    return response


def _consume_transaction(
    session: Session, state: str, kind: str
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Delete the unexpired transaction for ``state`` and return what it said.

    Committed before the provider is contacted, so the state is spent by the
    first callback that presents it. Of two concurrent callbacks, only the one
    whose DELETE removes the row proceeds.
    """
    row = session.execute(
        delete(SourceInstallTransaction)
        .where(
            SourceInstallTransaction.state_hash == hash_session_token(state),
            SourceInstallTransaction.kind == kind,
            SourceInstallTransaction.expires_at > datetime.now(timezone.utc),
        )
        .returning(
            SourceInstallTransaction.workspace_id,
            SourceInstallTransaction.user_id,
            SourceInstallTransaction.kind,
        )
    ).first()
    session.commit()
    if row is None:
        raise _install_failed()
    return row


@router.post(
    "/api/sources/{kind}/callback",
    response_model=ConnectionResponse,
    dependencies=[Depends(callback_limiter)],
)
def finish_install(
    kind: ChatKind,
    payload: InstallCallbackRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: DbSession,
    client_builder=Depends(get_oauth_client_builder),
) -> ConnectionResponse:
    """Complete the authorisation and store the connection."""
    _require_configured(kind)

    expected_state = request.cookies.get(INSTALL_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(
        expected_state, payload.state
    ):
        raise _install_failed()

    workspace_id, started_by, _ = _consume_transaction(session, payload.state, kind)
    # The person finishing must be the one who started, and must still hold the
    # permission: a role revoked while they were away at the provider applies here.
    if started_by != user.id:
        raise _install_failed()
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.SOURCES_WRITE
    )

    client = client_builder(kind)
    try:
        install = client.exchange_code(payload.code)
    except ChatInstallError:
        raise _install_failed()
    finally:
        client.close()

    credential = save_chat_credential(
        session,
        workspace_id=workspace_id,
        kind=kind,
        install=install,
        user_id=user.id,
    )
    session.commit()

    response.delete_cookie(
        key=INSTALL_STATE_COOKIE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path=INSTALL_STATE_COOKIE_PATH,
    )
    return ConnectionResponse(
        kind=credential.kind,
        external_ref=credential.external_ref,
        display_name=credential.display_name,
        installed_by_name=user.display_name,
        workspace_id=workspace_id,
    )


@router.get(
    "/api/workspaces/{workspace_id}/connections",
    response_model=list[ConnectionResponse],
)
def read_connections(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[ConnectionResponse]:
    """Which chat providers this workspace has connected.

    Any member may read it: knowing that Slack is connected is part of reading
    the workspace, and no token or scope is exposed.
    """
    load_workspace_for_user(session, user, workspace_id)
    connections = list_chat_connections(session, workspace_id)
    return [
        ConnectionResponse(
            kind=row.kind,
            external_ref=row.external_ref,
            display_name=row.display_name,
            installed_by_name=row.installer.display_name if row.installer else None,
            workspace_id=workspace_id,
        )
        for row in sorted(connections.values(), key=lambda r: r.kind)
    ]


@router.delete(
    "/api/workspaces/{workspace_id}/connections/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect(
    workspace_id: uuid.UUID,
    kind: ChatKind,
    user: CurrentUser,
    session: DbSession,
) -> None:
    """Stop future syncs from this provider.

    Already-ingested messages stay in the graph: disconnecting withdraws access,
    it does not retract what the workspace has already linked and cited.
    """
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.SOURCES_WRITE
    )
    if not delete_chat_credential(session, workspace_id=workspace_id, kind=kind):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{kind.title()} is not connected to this workspace",
        )
    session.commit()


def build_chat_client(kind: str, token: str) -> SlackClient | DiscordClient:
    """The read client for ``kind``. The caller closes it."""
    if kind == KIND_SLACK:
        return SlackClient(token)
    return DiscordClient(token)


def get_chat_client_builder():
    """Injectable so tests can supply a client with a mock transport."""
    return build_chat_client


def require_connection(session: Session, workspace_id: uuid.UUID, kind: str):
    """This workspace's credential for ``kind``, or a 409 telling the caller to
    connect it first. A missing connection is not a 404: the workspace exists
    and the fix is an action, not a different URL."""
    try:
        return get_chat_credential(session, workspace_id=workspace_id, kind=kind)
    except SourceCredentialMissing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No {kind.title()} source is connected. Authorise {kind.title()} first.",
        )


def chat_error_status(error: SourceError) -> int:
    if isinstance(error, SourceRateLimited):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(error, SourceUnauthorized):
        return status.HTTP_403_FORBIDDEN
    if isinstance(error, SourceNotFound):
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_502_BAD_GATEWAY


@router.get(
    "/api/workspaces/{workspace_id}/connections/{kind}/channels",
    response_model=list[ChannelOption],
)
def read_channels(
    workspace_id: uuid.UUID,
    kind: ChatKind,
    user: CurrentUser,
    session: DbSession,
    client_builder=Depends(get_chat_client_builder),
) -> list[ChannelOption]:
    """The channels available to ingest, for the picker.

    Requires ``sources.write`` rather than plain membership: this is a step in
    connecting a source, it spends the provider's rate limit, and the list
    itself discloses private channel names.
    """
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.SOURCES_WRITE
    )
    credential = require_connection(session, workspace_id, kind)

    client = client_builder(kind, credential.token)
    try:
        if kind == KIND_SLACK:
            channels = [
                ChannelOption(id=c.id, name=c.name or c.id)
                for c in client.list_channels()
            ]
        else:
            channels = [
                ChannelOption(id=c.id, name=c.name or c.id)
                for c in client.list_text_channels(credential.external_ref)
            ]
    except SourceError as error:
        raise HTTPException(status_code=chat_error_status(error), detail=str(error))
    finally:
        client.close()

    channels.sort(key=lambda c: (c.name.lower(), c.id))
    return channels
