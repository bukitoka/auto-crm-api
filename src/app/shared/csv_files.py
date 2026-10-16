"""CSV export and import helpers shared by the list endpoints.

Exports honor the list filters and sort. Imports read an uploaded file into one
dict per row; each module validates the rows with its `*Create` schema and creates
them through its service, collecting the outcome in an `ImportResult`.
"""

import csv
import io
import re
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import Response, UploadFile
from pydantic import BaseModel, ValidationError

from app.core.exceptions import BadRequestError, PayloadTooLargeError

IMPORT_MAX_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ERRORS = 50

# Spreadsheets run cells starting with these as formulas (CSV injection).
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
# ...but phone numbers and negative numbers are plain values.
_NUMBER_LIKE = re.compile(r"[+-][\d\s().-]*")


def _safe_cell(value: Any) -> Any:
    """Prefix formula-like text with an apostrophe; `read_csv` removes it again on import."""
    is_formula = isinstance(value, str) and value.startswith(FORMULA_STARTS)
    return f"'{value}" if is_formula and not _NUMBER_LIKE.fullmatch(value) else value


def _unescape(cell: str) -> str:
    return cell[1:] if cell.startswith("'") and cell[1:].startswith(FORMULA_STARTS) else cell


def to_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows([_safe_cell(value) for value in row] for row in rows)  # None: empty cell
    return output.getvalue()


def contact_name(contact: Any) -> str | None:
    """A related contact's full name for an export cell (None when there is no contact)."""
    return f"{contact.first_name} {contact.last_name or ''}".strip() if contact else None


def csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def read_csv(upload: UploadFile) -> list[tuple[int, dict[str, str]]]:
    """Read an uploaded CSV (size-limited) into `(row number, values)` pairs.

    Headers are normalized ("First Name" -> "first_name"), empty cells are dropped and
    blank lines skipped. Row numbers match the spreadsheet (the header is row 1).
    """
    data = await upload.read(IMPORT_MAX_BYTES + 1)
    if len(data) > IMPORT_MAX_BYTES:
        raise PayloadTooLargeError(f"CSV files can be at most {IMPORT_MAX_BYTES // 1024**2} MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadRequestError("The file must be a UTF-8 encoded CSV") from exc

    reader = csv.reader(io.StringIO(text))
    header = [name.strip().lower().replace(" ", "_") for name in next(reader, [])]
    if not any(header):
        raise BadRequestError("The CSV file is empty")
    rows = []
    for number, cells in enumerate(reader, start=2):
        values = {
            name: _unescape(cell.strip())
            for name, cell in zip(header, cells, strict=False)
            if cell.strip()
        }
        if values:
            rows.append((number, values))
    return rows


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    created: int = 0
    skipped: int = 0  # rows not created; the reasons are in `errors` (capped)
    errors: list[ImportRowError] = []

    def skip(self, row: int, message: str) -> None:
        self.skipped += 1
        if len(self.errors) < MAX_IMPORT_ERRORS:
            self.errors.append(ImportRowError(row=row, message=message))


def validation_message(exc: ValidationError) -> str:
    """The first validation problem of a row, e.g. `email: value is not a valid email`."""
    error = exc.errors()[0]
    field = ".".join(str(part) for part in error["loc"])
    return f"{field}: {error['msg']}" if field else error["msg"]
