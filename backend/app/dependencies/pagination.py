from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100).")] = 20,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(get_page_params)]

# `sort=-priority,due_date`: comma-separated fields, `-` for descending. Each field is
# checked against the endpoint's allowlist in the repository.
SortQuery = Annotated[
    str | None,
    Query(max_length=100, pattern=r"^-?[a-z_]+(,-?[a-z_]+)*$", description="e.g. `-created_at`"),
]
SearchQuery = Annotated[
    str | None,
    Query(min_length=1, max_length=100, description="Case-insensitive substring search."),
]
