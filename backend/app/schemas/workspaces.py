import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import PartialUpdate, RequestModel
from app.schemas.organizations import OrganizationName, Slug


class WorkspaceCreate(RequestModel):
    name: OrganizationName
    slug: Slug


class WorkspaceUpdate(PartialUpdate):
    name: OrganizationName | None = None
    slug: Slug | None = None


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
