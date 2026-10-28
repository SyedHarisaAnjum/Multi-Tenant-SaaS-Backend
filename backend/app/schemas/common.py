from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

T = TypeVar("T")


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, not silently ignored.

    So a client can't sneak in e.g. `organization_id`: tenant scope always comes from
    the authorized path/resource, never from the body.
    """

    model_config = ConfigDict(extra="forbid")


class PartialUpdate(RequestModel):
    """PATCH body. Omitted fields are left alone; `null` is only allowed where listed."""

    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required_fields(self) -> "PartialUpdate":
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError(f"'{name}' cannot be null.")
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent (explicit nulls included)."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int
