import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AIResponseError,
    AppError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
    app_error_handler,
    register_exception_handlers,
)
from app.modules.users.schemas import UserRead
from app.shared import utils
from app.shared.pagination import Page, PageParams
from app.shared.schemas import reject_null
from tests.unit.conftest import make_user

# --- utils ---


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        ("acme", "%acme%"),
        ("50%", "%50\\%%"),
        ("first_name", "%first\\_name%"),
        ("back\\slash", "%back\\\\slash%"),
    ],
)
def test_like_pattern_escapes_wildcards(search: str, expected: str) -> None:
    assert utils.like_pattern(search) == expected


def test_start_of_month_is_midnight_on_the_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "utc_now", lambda: datetime(2026, 3, 17, 15, 30, 5, tzinfo=UTC))

    assert utils.start_of_month_utc() == datetime(2026, 3, 1, tzinfo=UTC)


def test_today_utc_is_the_date_of_utc_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "utc_now", lambda: datetime(2026, 3, 17, 23, 59, tzinfo=UTC))

    assert utils.today_utc().isoformat() == "2026-03-17"


def test_utc_now_is_timezone_aware() -> None:
    assert utils.utc_now().tzinfo is UTC


# --- pagination ---


@pytest.mark.parametrize(("page", "size", "offset"), [(1, 20, 0), (2, 20, 20), (3, 50, 100)])
def test_page_params_offset(page: int, size: int, offset: int) -> None:
    assert PageParams(page=page, size=size).offset == offset


def test_page_from_items_converts_orm_objects() -> None:
    users = [make_user(full_name="Ada"), make_user(full_name="Bob")]

    page = Page[UserRead].from_items(users, total=7, params=PageParams(page=2, size=2))

    assert [user.full_name for user in page.items] == ["Ada", "Bob"]
    assert (page.total, page.page, page.size) == (7, 2, 2)


# --- schemas ---


def test_reject_null_passes_values_through() -> None:
    assert reject_null("value") == "value"
    assert reject_null(0) == 0


def test_reject_null_rejects_none() -> None:
    with pytest.raises(ValueError, match="may not be null"):
        reject_null(None)


# --- exceptions ---

REQUEST = Request(scope={"type": "http"})


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (AppError(), 400),
        (AuthenticationError(), 401),
        (PermissionDeniedError(), 403),
        (NotFoundError(), 404),
        (ConflictError(), 409),
        (AIResponseError(), 502),
        (ServiceUnavailableError(), 503),
    ],
)
def test_domain_errors_have_matching_status_codes(error: AppError, status_code: int) -> None:
    assert error.status_code == status_code
    assert error.message == error.default_message


async def test_app_error_handler_returns_detail_json() -> None:
    response = await app_error_handler(REQUEST, NotFoundError("Contact not found"))

    assert response.status_code == 404
    assert json.loads(bytes(response.body)) == {"detail": "Contact not found"}
    assert "www-authenticate" not in response.headers


async def test_authentication_errors_ask_for_a_bearer_token() -> None:
    response = await app_error_handler(REQUEST, AuthenticationError())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_registered_handler_turns_domain_errors_into_responses() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise ConflictError("Already exists")

    response = TestClient(app).get("/boom")

    assert response.status_code == 409
    assert response.json() == {"detail": "Already exists"}
