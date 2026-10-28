"""Pagination, sorting and search helpers. No database: statements are only compiled."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.exceptions import UnprocessableError, register_exception_handlers
from app.db.models import Project, Task
from app.dependencies.pagination import PageParams, Pagination, SortQuery
from app.repositories.project_repository import PROJECT_SORTS
from app.repositories.query_utils import apply_sort, contains_ci, total_pages
from app.repositories.task_repository import TASK_SORTS


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# --- pagination parameters ------------------------------------------------------

_app = FastAPI()
register_exception_handlers(_app)


@_app.get("/items")
def _items(params: Pagination, sort: SortQuery = None) -> dict[str, Any]:
    return {"page": params.page, "page_size": params.page_size, "offset": params.offset}


_client = TestClient(_app)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", {"page": 1, "page_size": 20, "offset": 0}),
        ("?page=3&page_size=10", {"page": 3, "page_size": 10, "offset": 20}),
        ("?page_size=1", {"page": 1, "page_size": 1, "offset": 0}),
        ("?page_size=100", {"page": 1, "page_size": 100, "offset": 0}),
    ],
)
def test_valid_pagination(query: str, expected: dict[str, int]) -> None:
    assert _client.get(f"/items{query}").json() == expected


@pytest.mark.parametrize(
    "query",
    ["?page=0", "?page=-1", "?page_size=0", "?page_size=101", "?page=abc", "?sort=name;drop"],
)
def test_invalid_pagination_is_422(query: str) -> None:
    response = _client.get(f"/items{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("total", "size", "pages"), [(0, 20, 0), (1, 20, 1), (20, 20, 1), (21, 20, 2)]
)
def test_total_pages(total: int, size: int, pages: int) -> None:
    assert total_pages(total, size) == pages


def test_offset() -> None:
    assert PageParams(page=5, page_size=25).offset == 100


# --- sorting --------------------------------------------------------------------


def test_sort_desc_and_multi_field_with_stable_tiebreaker() -> None:
    sql = _sql(apply_sort(select(Task), "-priority,due_date", TASK_SORTS, "-created_at", Task.id))
    order_by = sql.split("ORDER BY", 1)[1]
    assert "DESC NULLS LAST" in order_by
    assert "tasks.due_date ASC NULLS LAST" in order_by
    assert order_by.strip().endswith("tasks.id ASC")


def test_default_sort_used_when_none() -> None:
    sql = _sql(apply_sort(select(Project), None, PROJECT_SORTS, "-created_at", Project.id))
    assert "projects.created_at DESC NULLS LAST" in sql


@pytest.mark.parametrize("sort", ["description", "-password_hash", "name,organization_id"])
def test_sort_outside_allowlist_is_rejected(sort: str) -> None:
    with pytest.raises(UnprocessableError) as exc:
        apply_sort(select(Project), sort, PROJECT_SORTS, "name", Project.id)
    assert exc.value.code == "INVALID_SORT_FIELD"
    assert exc.value.details == [{"field": "query.sort", "allowed": sorted(PROJECT_SORTS)}]


# --- search ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("term", "pattern"),
    [
        ("login", "%login%"),
        ("100%", "%100\\%%"),  # user's % is literal
        ("a_b", "%a\\_b%"),  # user's _ is literal
        ("c:\\temp", "%c:\\\\temp%"),  # backslash escaped first
    ],
)
def test_contains_ci_escapes_wildcards(term: str, pattern: str) -> None:
    expr = contains_ci(Task.title, term)
    compiled = expr.compile(dialect=postgresql.dialect())
    assert "ILIKE" in str(compiled)
    assert "ESCAPE" in str(compiled)
    assert list(compiled.params.values()) == [pattern]
