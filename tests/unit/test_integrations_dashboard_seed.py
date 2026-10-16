import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import seed
from app.modules.activities.models import ActivityType
from app.modules.companies.models import Company
from app.modules.dashboard.service import RECENT_LIMIT, DashboardService
from app.modules.integrations.schemas import LeadIntake
from app.modules.integrations.service import IntegrationService
from app.modules.pipeline.service import PipelineService
from tests.unit.conftest import (
    make_activity,
    make_company,
    make_contact,
    make_deal,
    make_stage,
    make_task,
    make_user,
    mock_repos,
)


@pytest.fixture
def integrations(session: AsyncMock) -> IntegrationService:
    service = IntegrationService(session)
    mock_repos(service, "contacts", "companies", "activities", "contact_service")
    service.contacts.get_by_email.return_value = None
    service.companies.get_by_name.return_value = None
    service.contact_service.create.side_effect = lambda data, user: make_contact()
    return service


def _lead(**overrides: object) -> LeadIntake:
    return LeadIntake.model_validate({"first_name": "Leo", "email": "leo@startup.io"} | overrides)


async def test_new_lead_creates_a_contact_and_reports_created(
    integrations: IntegrationService,
) -> None:
    account = make_user()

    _, created = await integrations.ingest_lead(_lead(), user=account)

    assert created is True
    data = integrations.contact_service.create.call_args.args[0]
    assert (data.first_name, data.email, data.source) == ("Leo", "leo@startup.io", "web_form")
    assert data.company_id is None
    assert integrations.contact_service.create.call_args.kwargs["user"] is account


async def test_lead_with_unknown_company_creates_it(integrations: IntegrationService) -> None:
    account = make_user()

    def add(company: Company) -> Company:
        company.id = uuid.uuid7()  # the database would assign the id on flush
        return company

    integrations.companies.add.side_effect = add

    await integrations.ingest_lead(_lead(company_name="Startup IO"), user=account)

    company = integrations.companies.add.call_args.args[0]
    assert (company.name, company.owner_id) == ("Startup IO", account.id)
    data = integrations.contact_service.create.call_args.args[0]
    assert data.company_id is not None
    assert data.company_id == company.id


async def test_lead_with_known_company_reuses_it(integrations: IntegrationService) -> None:
    existing = make_company(name="Startup IO")
    integrations.companies.get_by_name.return_value = existing

    await integrations.ingest_lead(_lead(company_name="startup io"), user=make_user())

    integrations.companies.add.assert_not_awaited()
    assert integrations.contact_service.create.call_args.args[0].company_id == existing.id


async def test_existing_email_returns_the_existing_contact(
    integrations: IntegrationService,
) -> None:
    existing = make_contact(email="leo@startup.io")
    integrations.contacts.get_by_email.return_value = existing
    integrations.contact_service.get.return_value = existing

    contact, created = await integrations.ingest_lead(_lead(), user=make_user())

    assert created is False
    assert contact is existing
    integrations.contact_service.create.assert_not_awaited()


async def test_lead_message_is_saved_as_a_note(integrations: IntegrationService) -> None:
    account = make_user()

    await integrations.ingest_lead(_lead(message="Call me", source="landing"), user=account)

    note = integrations.activities.add.call_args.args[0]
    assert note.type == ActivityType.NOTE
    assert note.subject == "Message via landing"
    assert note.body == "Call me"
    assert note.created_by_id == account.id


async def test_lead_without_message_adds_no_note(integrations: IntegrationService) -> None:
    await integrations.ingest_lead(_lead(), user=make_user())

    integrations.activities.add.assert_not_awaited()


async def test_dashboard_summary_combines_the_repository_numbers(session: AsyncMock) -> None:
    user = make_user()
    stage = make_stage("Proposal")
    service = DashboardService(session)
    mock_repos(service, "repo", "activities", "tasks")
    service.repo.open_pipeline_value.return_value = Decimal("1500.50")
    service.repo.closed_deals_since.side_effect = [
        SimpleNamespace(won_count=1, lost_count=2, won_value=Decimal("40")),  # this month
        SimpleNamespace(won_count=3, lost_count=1, won_value=Decimal("300")),  # last 90 days
    ]
    service.repo.contacts_created_since.return_value = 3
    service.repo.pipeline_by_stage.return_value = [
        SimpleNamespace(
            stage_id=stage.id, stage_name="Proposal", deal_count=2, total_value=Decimal("99.5")
        )
    ]
    service.repo.contacts_by_status.return_value = {"lead": 5}
    service.repo.activities_by_type_since.return_value = {"call": 2}
    service.repo.open_tasks_due_between.side_effect = [1, 4]
    service.repo.overdue_tasks.return_value = [make_task(title="Late")]
    service.repo.open_deals_closing_between.return_value = [make_deal(title="Soon")]
    service.repo.leaderboard.return_value = [
        SimpleNamespace(
            User=user, open_deals_value=Decimal(10), won_this_month_value=Decimal(0), open_tasks=2
        )
    ]
    service.activities.list_recent.return_value = [make_activity()]
    service.tasks.list_open_for_assignee.return_value = [make_task(title="Mine")]
    service.tasks.count_overdue.return_value = 4

    summary = await service.summary(user)

    assert summary.open_pipeline_value == 1500.5
    assert summary.won_this_month_value == 40.0
    assert (summary.deals_won_this_month, summary.deals_lost_this_month) == (1, 2)
    assert summary.win_rate == 0.75
    assert summary.average_deal_size == 100.0
    assert summary.new_leads_this_month == 3
    assert summary.overdue_tasks == 4
    assert (summary.tasks_due_today, summary.tasks_due_this_week) == (1, 4)
    assert summary.pipeline_by_stage[0].model_dump() == {
        "stage_id": stage.id,
        "stage_name": "Proposal",
        "deal_count": 2,
        "total_value": 99.5,
    }
    assert [(c.status, c.count) for c in summary.contacts_by_status] == [
        ("lead", 5),
        ("prospect", 0),
        ("customer", 0),
        ("churned", 0),
    ]
    assert {str(a.type): a.count for a in summary.activities_last_30_days}["call"] == 2
    assert [task.title for task in summary.overdue_task_list] == ["Late"]
    assert [deal.title for deal in summary.deals_closing_soon] == ["Soon"]
    assert summary.team[0].user.id == user.id
    assert summary.team[0].open_tasks == 2
    assert [task.title for task in summary.my_tasks] == ["Mine"]
    assert len(summary.recent_activities) == 1
    service.tasks.list_open_for_assignee.assert_awaited_once_with(user.id, limit=RECENT_LIMIT)
    month_start = service.repo.closed_deals_since.call_args_list[0].args[0]
    assert (month_start.day, month_start.hour, month_start.minute) == (1, 0, 0)


async def test_dashboard_rates_are_null_without_closed_deals(session: AsyncMock) -> None:
    service = DashboardService(session)
    mock_repos(service, "repo", "activities", "tasks")
    service.repo.open_pipeline_value.return_value = Decimal(0)
    service.repo.closed_deals_since.return_value = SimpleNamespace(
        won_count=0, lost_count=0, won_value=Decimal(0)
    )
    for name in ("pipeline_by_stage", "overdue_tasks", "open_deals_closing_between", "leaderboard"):
        getattr(service.repo, name).return_value = []
    service.repo.contacts_by_status.return_value = {}
    service.repo.activities_by_type_since.return_value = {}
    service.repo.contacts_created_since.return_value = 0
    service.repo.open_tasks_due_between.return_value = 0
    service.activities.list_recent.return_value = []
    service.tasks.list_open_for_assignee.return_value = []
    service.tasks.count_overdue.return_value = 0

    summary = await service.summary(make_user())

    assert (summary.win_rate, summary.average_deal_size) == (None, None)


async def test_pipeline_lists_stages_with_deal_counts(session: AsyncMock) -> None:
    service = PipelineService(session)
    mock_repos(service, "repo")
    stages = [make_stage("Qualification"), make_stage("Won")]
    service.repo.list_stages.return_value = stages
    service.repo.deal_counts.return_value = {stages[0].id: 3}

    result = await service.list_stages()

    assert [(stage.name, stage.deal_count) for stage in result] == [
        ("Qualification", 3),
        ("Won", 0),
    ]


@pytest.mark.parametrize(
    ("name", "protected"),
    [("auto_crm", False), ("auto_crm_test", True), ("auto_crm_e2e", True), (None, False)],
)
def test_seeder_protects_test_and_e2e_databases(name: str | None, protected: bool) -> None:
    assert seed.is_protected_database(name) is protected


def test_seeder_refuses_a_test_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # tests/conftest.py points DATABASE_URL at auto_crm_test.
    monkeypatch.setattr("sys.argv", ["seed"])
    run = AsyncMock()
    monkeypatch.setattr(seed, "seed", run)

    with pytest.raises(SystemExit) as exit_info:
        seed.main()

    assert exit_info.value.code == 1
    assert "Refusing" in capsys.readouterr().out
    run.assert_not_awaited()


def test_seeder_runs_with_reset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["seed", "--reset"])
    monkeypatch.setattr(seed.settings, "database_url", "postgresql+asyncpg://u:p@db:5432/demo")
    monkeypatch.setattr(seed, "engine", AsyncMock())
    run = AsyncMock(return_value=0)
    monkeypatch.setattr(seed, "seed", run)

    with pytest.raises(SystemExit) as exit_info:
        seed.main()

    assert exit_info.value.code == 0
    run.assert_awaited_once_with(reset=True)


def test_slug_makes_domain_friendly_names() -> None:
    assert seed._slug("Smith, Jones & Co.") == "smith-jones-co"
    assert seed._slug("Hall PLC") == "hall-plc"
