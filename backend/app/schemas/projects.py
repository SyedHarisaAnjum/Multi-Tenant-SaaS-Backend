import uuid
from datetime import datetime
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.db.models import ProjectStatus
from app.schemas.common import PartialUpdate, RequestModel

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=10_000)]
Version = Annotated[int, Field(ge=1, description="The `version` you last read (optimistic lock).")]


class ProjectCreate(RequestModel):
    workspace_id: uuid.UUID
    name: ProjectName
    description: Description | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE


class ProjectUpdate(PartialUpdate):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"description"})

    version: Version
    name: ProjectName | None = None
    description: Description | None = None
    status: ProjectStatus | None = None
    workspace_id: uuid.UUID | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    version: int
    created_at: datetime
    updated_at: datetime
