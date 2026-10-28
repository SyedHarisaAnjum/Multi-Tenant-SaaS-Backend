from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.repositories.user_repository import UserRepository

# auto_error=False so missing credentials go through our own 401 error format.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated.")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise AuthenticationError(
            "Invalid or expired access token.", code="INVALID_ACCESS_TOKEN"
        ) from None

    user = UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid or expired access token.", code="INVALID_ACCESS_TOKEN")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
