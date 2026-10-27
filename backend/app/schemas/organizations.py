import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.db.models import MembershipRole

OrganizationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Slug = Annotated[
    str,
    Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Lowercase letters, digits and single hyphens, e.g. `acme-inc`.",
    ),
]


class OrganizationCreate(BaseModel):
    name: OrganizationName
    slug: Slug


class OrganizationUpdate(BaseModel):
    name: OrganizationName | None = None
    slug: Slug | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class OrganizationWithRole(OrganizationRead):
    """An organization as seen by the caller, including their role in it."""

    role: MembershipRole
