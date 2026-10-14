"""Shared pagination: query params dependency and the `Page[T]` response schema."""

from collections.abc import Sequence
from typing import Annotated, Any, Self

from fastapi import Depends, Query
from pydantic import BaseModel


class PageParams:
    """`?page=1&size=20` query parameters."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> None:
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


PageParamsDep = Annotated[PageParams, Depends()]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int

    @classmethod
    def from_items(cls, items: Sequence[Any], total: int, params: PageParams) -> Self:
        """Build a page from ORM objects (converted with `from_attributes`)."""
        return cls.model_validate(
            {"items": items, "total": total, "page": params.page, "size": params.size},
            from_attributes=True,
        )
