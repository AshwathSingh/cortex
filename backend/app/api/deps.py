"""Shared request dependencies.

Contains the temporary authentication seam US-41 is built against.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.postgres import get_session

# Header carrying the caller's user id until real sessions land.
USER_HEADER = "X-Cortex-User"


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    x_cortex_user: Annotated[str | None, Header(alias=USER_HEADER)] = None,
) -> User:
    """Resolve the calling user.
    TODO: CHANGE FROM BELOW CODE TO ACTUAL LOGGING IN. THIS IS A PASS FOR US 41 TO WORK.
          US-38 IMPLEMENTS LOGGING IN.

    NOT SAFE TO DEPLOY: any caller can claim any user id. It exists so the
    workspace endpoints can be built and exercised ahead of authentication.
    """
    if not x_cortex_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": USER_HEADER},
        )

    try:
        user_id = uuid.UUID(x_cortex_user)
    except ValueError:
        # A malformed id is an auth failure.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    user = session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_session)]
