import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import RequestModel


def normalize_email(email: str) -> str:
    """Single canonical form for every email we store or look up."""
    return email.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]

# Upper bound keeps hashing cost bounded against oversized inputs.
Password = Annotated[str, Field(min_length=12, max_length=128)]


class RegisterRequest(RequestModel):
    email: NormalizedEmail
    password: Password
    full_name: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class LoginRequest(RequestModel):
    email: NormalizedEmail
    # Don't enforce the registration policy on login: it would leak the policy
    # and reject accounts created under an older one.
    password: Annotated[str, Field(min_length=1, max_length=128)]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime
