from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.core.config import get_settings
from app.dependencies.auth import CurrentUser, DbSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

# The refresh token travels only in an HttpOnly cookie so page JavaScript can never
# read it. The access token is returned in the body and should be kept in memory.
RefreshCookie = Annotated[str | None, Cookie(alias=get_settings().refresh_cookie_name)]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _token_response(response: Response, tokens: IssuedTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: DbSession) -> UserRead:
    user = AuthService(db).register(data)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, db: DbSession) -> TokenResponse:
    return _token_response(response, AuthService(db).login(data))


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response, db: DbSession, refresh_token: RefreshCookie = None
) -> TokenResponse:
    return _token_response(response, AuthService(db).refresh(refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: DbSession, refresh_token: RefreshCookie = None) -> None:
    AuthService(db).logout(refresh_token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
