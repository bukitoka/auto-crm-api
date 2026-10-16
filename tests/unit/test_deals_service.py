from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.events import Event
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.deals import service as deal_service_module
from app.modules.deals.schemas import DealCreate, DealFilters, DealUpdate
from app.modules.deals.service import DealService
from app.shared.pagination import PageParams
from tests.unit.conftest import event_names, make_deal, make_stage, make_user, mock_repos

Published = list[tuple[Event, dict[str, Any]]]
CLOSED_AT = datetime(2026, 2, 1, 9, 30, tzinfo=UTC)

QUALIFICATION = make_stage("Qualification", position=1)
PROPOSAL = make_stage("Proposal", position=2)
WON = make_stage("Won", position=4)
LOST = make_stage("Lost", position=5)
STAGES = {stage.id: stage for stage in [QUALIFICATION, PROPOSAL, WON, LOST]}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deal_service_module, "utc_now", lambda: CLOSED_AT)


@pytest.fixture
def service(session: AsyncMock) -> DealService:
    service = DealService(session)
    mock_repos(service, "repo", "pipeline", "contacts", "companies", "users")
    service.pipeline.get_default_stage.return_value = QUALIFICATION
    service.pipeline.get_stage.side_effect = lambda stage_id: STAGES.get(stage_id)
    return service


def _reload_with_stage(service: DealService, deal: Any) -> None:
    """After commit the service reloads the deal; mimic the reload picking up the new stage."""

    async def get(_deal_id: Any) -> Any:
        deal.stage = STAGES[deal.stage_id]
        return deal

    service.repo.get.side_effect = get


async def test_create_uses_first_open_stage_usd_and_current_user(
    service: DealService, published_events: Published
) -> None:
    user = make_user()
    service.repo.get.return_value = make_deal()

    await service.create(DealCreate(title="New deal", currency="eur"), user=user)

    added = service.repo.add.call_args.args[0]
    assert added.stage_id == QUALIFICATION.id
    assert added.currency == "EUR"  # upper-cased
    assert added.owner_id == user.id
    assert added.closed_at is None
    assert event_names(published_events) == [Event.DEAL_CREATED]


async def test_create_defaults_currency_to_usd(
    service: DealService, published_events: Published
) -> None:
    service.repo.get.return_value = make_deal()

    await service.create(DealCreate(title="New deal"), user=make_user())

    assert service.repo.add.call_args.args[0].currency == "USD"


@pytest.mark.parametrize("stage", [WON, LOST], ids=["won", "lost"])
async def test_create_in_a_closed_stage_sets_closed_at(
    service: DealService, published_events: Published, stage: Any
) -> None:
    service.repo.get.return_value = make_deal(stage=stage)

    await service.create(DealCreate(title="Done deal", stage_id=stage.id), user=make_user())

    assert service.repo.add.call_args.args[0].closed_at == CLOSED_AT


async def test_create_without_any_stage_conflicts(service: DealService) -> None:
    service.pipeline.get_default_stage.return_value = None

    with pytest.raises(ConflictError, match="No pipeline stages"):
        await service.create(DealCreate(title="Deal"), user=make_user())


async def test_create_with_unknown_stage_is_not_found(service: DealService) -> None:
    with pytest.raises(NotFoundError, match="Pipeline stage not found"):
        await service.create(DealCreate(title="Deal", stage_id=make_stage().id), user=make_user())


@pytest.mark.parametrize(
    ("field", "repo", "message"),
    [
        ("contact_id", "contacts", "Contact not found"),
        ("company_id", "companies", "Company not found"),
        ("owner_id", "users", "Owner not found"),
    ],
)
async def test_create_with_unknown_reference_is_not_found(
    service: DealService, field: str, repo: str, message: str
) -> None:
    getattr(service, repo).exists.return_value = False
    getattr(service, repo).get.return_value = None

    with pytest.raises(NotFoundError, match=message):
        await service.create(
            DealCreate.model_validate({"title": "Deal", field: make_user().id}), user=make_user()
        )


async def test_moving_to_won_sets_closed_at_and_emits_events(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=QUALIFICATION)
    _reload_with_stage(service, deal)

    result = await service.change_stage(deal.id, WON.id)

    assert result.stage_id == WON.id
    assert result.closed_at == CLOSED_AT
    assert event_names(published_events) == [Event.DEAL_STAGE_CHANGED, Event.DEAL_WON]
    stage_changed = published_events[0][1]
    assert stage_changed["previous_stage"] == {
        "id": str(QUALIFICATION.id),
        "name": "Qualification",
        "is_won": False,
        "is_lost": False,
    }
    assert stage_changed["stage"]["name"] == "Won"
    assert "previous_stage" not in published_events[1][1]


async def test_moving_to_lost_emits_deal_lost(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=PROPOSAL)
    _reload_with_stage(service, deal)

    await service.change_stage(deal.id, LOST.id)

    assert deal.closed_at == CLOSED_AT
    assert event_names(published_events) == [Event.DEAL_STAGE_CHANGED, Event.DEAL_LOST]


async def test_reopening_a_won_deal_clears_closed_at(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=WON, closed_at=CLOSED_AT)
    _reload_with_stage(service, deal)

    await service.change_stage(deal.id, PROPOSAL.id)

    assert deal.closed_at is None
    assert event_names(published_events) == [Event.DEAL_STAGE_CHANGED]
    assert published_events[0][1]["previous_stage"]["name"] == "Won"


async def test_moving_to_the_same_stage_emits_nothing(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=PROPOSAL)
    _reload_with_stage(service, deal)

    await service.change_stage(deal.id, PROPOSAL.id)

    assert published_events == []
    service.pipeline.get_stage.assert_not_awaited()


async def test_moving_to_unknown_stage_is_not_found(service: DealService) -> None:
    deal = make_deal(stage=PROPOSAL)
    _reload_with_stage(service, deal)

    with pytest.raises(NotFoundError, match="Pipeline stage not found"):
        await service.change_stage(deal.id, make_stage("Ghost").id)
    service.session.commit.assert_not_awaited()


async def test_patch_with_stage_id_behaves_like_change_stage(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=QUALIFICATION, title="Old")
    _reload_with_stage(service, deal)

    await service.update(deal.id, DealUpdate(title="New", currency="gbp", stage_id=WON.id))

    assert (deal.title, deal.currency, deal.stage_id) == ("New", "GBP", WON.id)
    assert event_names(published_events) == [Event.DEAL_STAGE_CHANGED, Event.DEAL_WON]


async def test_patch_without_stage_emits_nothing(
    service: DealService, published_events: Published
) -> None:
    deal = make_deal(stage=QUALIFICATION)
    _reload_with_stage(service, deal)

    await service.update(deal.id, DealUpdate(title="Renamed"))

    assert deal.title == "Renamed"
    assert published_events == []


async def test_get_unknown_deal_is_not_found(service: DealService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Deal not found"):
        await service.get(make_deal().id)


async def test_delete_removes_the_deal(service: DealService) -> None:
    deal = make_deal()
    service.repo.get.return_value = deal

    await service.delete(deal.id)

    service.repo.delete.assert_awaited_once_with(deal)


async def test_list_page_returns_values_as_numbers(service: DealService) -> None:
    service.repo.list_page.return_value = ([make_deal()], 1)

    page = await service.list_page(DealFilters(), PageParams())

    assert page.items[0].value == 1000.0
