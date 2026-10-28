"""Reusable list-query helpers. Callers build a statement that is *already* filtered to
the caller's tenant; these only sort, search and paginate it."""

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, Select, SQLColumnExpression, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.exceptions import UnprocessableError
from app.dependencies.pagination import PageParams

T = TypeVar("T")

SortColumns = Mapping[str, SQLColumnExpression[Any]]


def contains_ci(column: InstrumentedAttribute[str], term: str) -> ColumnElement[bool]:
    """`column ILIKE '%term%'`, with the user's % and _ treated literally."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def apply_sort(
    stmt: Select[Any],
    sort: str | None,
    allowed: SortColumns,
    default: str,
    tiebreaker: InstrumentedAttribute[Any],
) -> Select[Any]:
    order_by = []
    for raw in (sort or default).split(","):
        descending = raw.startswith("-")
        name = raw.lstrip("-")
        if name not in allowed:
            raise UnprocessableError(
                f"Cannot sort by '{name}'.",
                code="INVALID_SORT_FIELD",
                details=[{"field": "query.sort", "allowed": sorted(allowed)}],
            )
        column = allowed[name]
        order_by.append(column.desc().nulls_last() if descending else column.asc().nulls_last())
    # A unique tiebreaker keeps pages stable when sort values repeat.
    return stmt.order_by(*order_by, tiebreaker.asc())


def paginate(db: Session, stmt: Select[Any], params: PageParams) -> tuple[Sequence[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
    return items, total


def total_pages(total: int, page_size: int) -> int:
    return ceil(total / page_size) if total else 0
