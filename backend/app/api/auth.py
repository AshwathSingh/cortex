"""Email/password authentication with revocable cookie sessions."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.config import settings
from app.db.postgres import get_session
from app.models import User, UserSession
from app.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from app.services.workspaces import create_workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])
DbSession = Annotated[Session, Depends(get_session)]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=15, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


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
            name=f"{display_name}'s Workspace" if display_name else "My Workspace",
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
