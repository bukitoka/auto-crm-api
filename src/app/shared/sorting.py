"""Sorting for list endpoints: `?sort=<field>&order=asc|desc`.

Each `*Filters` schema declares its sortable fields as a `Literal` (so unknown
fields are rejected with 422) and maps them to columns in its repository.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, UnaryExpression
from sqlalchemy.orm import InstrumentedAttribute


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


def sort_by(
    column: ColumnElement[Any] | InstrumentedAttribute[Any], order: SortOrder
) -> UnaryExpression[Any]:
    """`column ASC|DESC`, with empty values last in both directions."""
    return (column.desc() if order == SortOrder.DESC else column.asc()).nulls_last()
