"""Email/password and GitHub OAuth authentication with revocable cookie sessions.

GitHub sign-in (US-1) runs in two steps:

    GET  /api/auth/github/login     -> sets a state cookie, 302 to GitHub
    POST /api/auth/github/callback  {"code", "state"} from the frontend callback page

Both steps end in the same session cookie as email/password login. The GitHub
access token is stored encrypted (``GitHubCredential``) and never returned.
"""

import secrets
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.config import settings
from app.db.postgres import get_session
from app.github.oauth import (
    GitHubIdentity,
    GitHubOAuthClient,
    OAuthError,
    OAuthToken,
    authorize_url,
)
from app.models import GitHubCredential, User, UserSession
from app.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from app.services.workspaces import create_workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_session)]

OAUTH_STATE_COOKIE = "cortex_oauth_state"
# Scoped to the callback so the state is not sent with every API request.
OAUTH_STATE_COOKIE_PATH = "/api/auth/github"
OAUTH_STATE_TTL_SECONDS = 10 * 60


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=15, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GitHubCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=1, max_length=512)


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str | None


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id), email=user.email, display_name=user.display_name
    )


def _create_session(user: User, session: Session) -> tuple[str, datetime]:
    token = new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )
    )
    return token, expires_at


def _default_workspace_name(display_name: str | None) -> str:
    return f"{display_name}'s Workspace" if display_name else "My Workspace"


def _set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        expires=expires_at,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, response: Response, session: DbSession) -> UserResponse:
    email = str(payload.email).strip().lower()
    display_name = payload.display_name.strip() if payload.display_name else None
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=display_name,
        email_verified_at=None,
    )
    session.add(user)

    try:
        session.flush()
        create_workspace(
            session,
            name=_default_workspace_name(display_name),
            owner=user,
        )
        token, expires_at = _create_session(user, session)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from error

    _set_session_cookie(response, token, expires_at)
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, session: DbSession) -> UserResponse:
    email = str(payload.email).strip().lower()
    user = session.scalar(select(User).where(func.lower(User.email) == email))

    if (
        user is None
        or not user.is_active
        or user.password_hash is None
        or not verify_password(user.password_hash, payload.password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token, expires_at = _create_session(user, session)
    session.commit()
    _set_session_cookie(response, token, expires_at)
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: DbSession) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        session.execute(
            delete(UserSession).where(
                UserSession.token_hash == hash_session_token(token)
            )
        )
        session.commit()

    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.get("/me", response_model=UserResponse)
def current_user(user: CurrentUser) -> UserResponse:
    return _user_response(user)


def _require_github_oauth() -> None:
    if not settings.github_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub sign-in is not configured",
        )


def get_github_oauth_client() -> Iterator[GitHubOAuthClient]:
    _require_github_oauth()
    client = GitHubOAuthClient(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret.get_secret_value(),
        redirect_uri=settings.github_oauth_redirect_uri,
    )
    try:
        yield client
    finally:
        client.close()


@router.get("/github/login")
def github_login() -> RedirectResponse:
    """Start GitHub sign-in: bind a random state to this browser, then hand off."""
    _require_github_oauth()
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(
        authorize_url(
            client_id=settings.github_client_id,
            redirect_uri=settings.github_oauth_redirect_uri,
            scope=settings.github_oauth_scope,
            state=state,
        ),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        # Lax still sends the cookie on the same-origin POST from the callback page.
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
    )
    return response


def _github_sign_in_failed() -> HTTPException:
    # One message for every rejection, so the response does not say which check failed.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="GitHub sign-in failed. Please try again.",
    )


def _resolve_github_user(
    session: Session, identity: GitHubIdentity, token: OAuthToken
) -> User:
    """The Cortex user for this GitHub account, creating one on first sign-in."""
    user = session.scalar(select(User).where(User.github_id == identity.id))

    if user is None:
        email = identity.email.strip().lower()
        # Never auto-link to an existing email/password account: Cortex does not
        # verify signup emails, so whoever registered that address first could be
        # an attacker waiting for the real owner to sign in with GitHub.
        if session.scalar(select(User.id).where(func.lower(User.email) == email)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An account with this email already exists. "
                    "Log in with your email and password instead."
                ),
            )
        display_name = (identity.name or identity.login)[:100]
        user = User(
            email=email,
            password_hash=None,
            github_id=identity.id,
            github_login=identity.login,
            display_name=display_name,
            avatar_url=identity.avatar_url,
            email_verified_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.flush()
        create_workspace(
            session, name=_default_workspace_name(display_name), owner=user
        )
    elif not user.is_active:
        raise _github_sign_in_failed()
    else:
        user.github_login = identity.login
        user.avatar_url = identity.avatar_url

    credential = session.get(GitHubCredential, user.id)
    if credential is None:
        session.add(
            GitHubCredential(
                user_id=user.id, access_token=token.access_token, scope=token.scope
            )
        )
    else:
        credential.access_token = token.access_token
        credential.scope = token.scope
    return user


@router.post("/github/callback", response_model=UserResponse)
def github_callback(
    payload: GitHubCallbackRequest,
    request: Request,
    response: Response,
    session: DbSession,
    oauth: Annotated[GitHubOAuthClient, Depends(get_github_oauth_client)],
) -> UserResponse:
    """Finish GitHub sign-in. Any rejection aborts with 401 and no session."""
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(
        expected_state.encode(), payload.state.encode()
    ):
        raise _github_sign_in_failed()

    try:
        token = oauth.exchange_code(payload.code)
        identity = oauth.fetch_identity(token.access_token)
    except OAuthError as error:
        raise _github_sign_in_failed() from error
    except httpx.TransportError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach GitHub. Please try again.",
        ) from error

    try:
        user = _resolve_github_user(session, identity, token)
        session_token, expires_at = _create_session(user, session)
        session.commit()
    except IntegrityError as error:
        # Two first sign-ins racing for the same GitHub account or email.
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account was just created. Please try signing in again.",
        ) from error

    _set_session_cookie(response, session_token, expires_at)
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
    )
    return _user_response(user)
