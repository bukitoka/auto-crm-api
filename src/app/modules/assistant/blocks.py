"""Rich parts of an assistant reply: charts, metric cards and tables.

The model fills these in through the `show_*` tools with numbers it got from the data tools.
They are validated here and stored with the message, so the web app can draw them.
"""

import math
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_CATEGORIES = 24
MAX_SERIES = 4
MAX_METRICS = 6
MAX_COLUMNS = 6
MAX_ROWS = 25


class ChartSeries(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    values: list[float]

    @field_validator("values")
    @classmethod
    def _finite(cls, values: list[float]) -> list[float]:
        if not all(math.isfinite(v) for v in values):
            raise ValueError("values must be finite numbers")
        return values


class ChartBlock(BaseModel):
    """A bar, line or pie chart. The title should be the question the chart answers."""

    type: Literal["chart"] = "chart"
    kind: Literal["bar", "line", "pie"]
    title: str = Field(min_length=1, max_length=120)
    unit: Literal["number", "currency", "percent"] = "number"
    categories: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=1, max_length=MAX_CATEGORIES
    )
    series: list[ChartSeries] = Field(min_length=1, max_length=MAX_SERIES)

    @model_validator(mode="after")
    def _consistent(self) -> ChartBlock:
        for series in self.series:
            if len(series.values) != len(self.categories):
                raise ValueError(
                    f"series {series.name!r} has {len(series.values)} values "
                    f"for {len(self.categories)} categories"
                )
        if self.kind == "pie":
            if len(self.series) != 1:
                raise ValueError("a pie chart takes exactly one series")
            if any(v < 0 for v in self.series[0].values):
                raise ValueError("a pie chart cannot show negative values")
        return self


class Metric(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=30, description="Already formatted, e.g. $12,400")
    hint: str | None = Field(default=None, max_length=80)


class MetricsBlock(BaseModel):
    """A row of headline numbers."""

    type: Literal["metrics"] = "metrics"
    title: str | None = Field(default=None, max_length=120)
    items: list[Metric] = Field(min_length=1, max_length=MAX_METRICS)


class RowLink(BaseModel):
    entity: Literal["contact", "company", "deal"]
    id: uuid.UUID


class TableBlock(BaseModel):
    """A small table. `row_links` makes a row open its record."""

    type: Literal["table"] = "table"
    title: str = Field(min_length=1, max_length=120)
    columns: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=1, max_length=MAX_COLUMNS
    )
    rows: list[list[str | float | None]] = Field(min_length=1, max_length=MAX_ROWS)
    row_links: list[RowLink | None] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> TableBlock:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError(f"every row needs {len(self.columns)} cells, one per column")
        if self.row_links is not None and len(self.row_links) != len(self.rows):
            raise ValueError("row_links needs one entry (or null) per row")
        return self


AssistantBlock = Annotated[ChartBlock | MetricsBlock | TableBlock, Field(discriminator="type")]
