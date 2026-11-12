from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.modules.dashboard import service as dashboard_module
from app.modules.dashboard.service import DashboardService
from tests.unit.conftest import mock_repos


@pytest.mark.parametrize(
    ("current_month", "months", "expected_months"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), 3, ["2025-11", "2025-12", "2026-01"]),
        (datetime(2024, 3, 1, tzinfo=UTC), 2, ["2024-02", "2024-03"]),
    ],
)
async def test_monthly_trend_keeps_calendar_order_and_fills_missing_months(
    session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    current_month: datetime,
    months: int,
    expected_months: list[str],
) -> None:
    monkeypatch.setattr(dashboard_module, "start_of_month_utc", lambda: current_month)
    service = DashboardService(session)
    mock_repos(service, "repo")
    service.repo.monthly_totals.return_value = {expected_months[-1]: 125.0}

    series = await service.monthly_trend("won_value", months)

    assert series == [
        (month, 125.0 if month == expected_months[-1] else 0.0) for month in expected_months
    ]
    expected_since = datetime.fromisoformat(f"{expected_months[0]}-01T00:00:00+00:00")
    service.repo.monthly_totals.assert_awaited_once_with("won_value", expected_since)
