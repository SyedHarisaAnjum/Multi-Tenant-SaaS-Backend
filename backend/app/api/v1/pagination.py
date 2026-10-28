from collections.abc import Sequence
from typing import Any, TypeVar

from fastapi import Response
from pydantic import BaseModel

from app.dependencies.pagination import PageParams
from app.repositories.query_utils import total_pages
from app.schemas.common import Page

ReadModel = TypeVar("ReadModel", bound=BaseModel)


def to_page(
    model: type[ReadModel], items: Sequence[Any], total: int, params: PageParams
) -> Page[ReadModel]:
    return Page[model](  # type: ignore[valid-type]
        items=[model.model_validate(item) for item in items],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=total_pages(total, params.page_size),
    )


def mark_cache(response: Response, hit: bool) -> None:
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
