import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


@pytest.mark.parametrize("raw", ["Alice@Example.COM", "  alice@example.com  ", "ALICE@EXAMPLE.COM"])
def test_emails_are_normalized(raw: str) -> None:
    assert RegisterRequest(email=raw, password="x" * 12).email == "alice@example.com"
    assert LoginRequest(email=raw, password="x").email == "alice@example.com"


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="x" * 12)


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_length_is_enforced_on_register(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="alice@example.com", password=password)
