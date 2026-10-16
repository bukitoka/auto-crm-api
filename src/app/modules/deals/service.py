import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.events import Event
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.companies.repository import CompanyRepository
from app.modules.contacts.repository import ContactRepository
from app.modules.deals.models import Deal
from app.modules.deals.repository import DealRepository
from app.modules.deals.schemas import DealCreate, DealFilters, DealRead, DealUpdate
from app.modules.pipeline.models import PipelineStage
from app.modules.pipeline.repository import PipelineRepository
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.shared.csv_files import contact_name, to_csv
from app.shared.pagination import Page, PageParams
from app.shared.schemas import StageRef
from app.shared.utils import utc_now

CSV_COLUMNS = [
    "title",
    "value",
    "currency",
    "stage",
    "contact",
    "company",
    "owner",
    "expected_close_date",
    "closed_at",
    "created_at",
]


class DealService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DealRepository(session)
        self.pipeline = PipelineRepository(session)
        self.contacts = ContactRepository(session)
        self.companies = CompanyRepository(session)
        self.users = UserRepository(session)

    async def get(self, deal_id: uuid.UUID) -> Deal:
        deal = await self.repo.get(deal_id)
        if deal is None:
            raise NotFoundError("Deal not found")
        return deal

    async def list_page(self, filters: DealFilters, params: PageParams) -> Page[DealRead]:
        items, total = await self.repo.list_page(filters, offset=params.offset, limit=params.size)
        return Page[DealRead].from_items(items, total, params)

    async def export_csv(self, filters: DealFilters) -> str:
        deals = await self.repo.list_all(filters)
        return to_csv(
            CSV_COLUMNS,
            (
                [
                    deal.title,
                    deal.value,
                    deal.currency,
                    deal.stage.name,
                    contact_name(deal.contact),
                    deal.company.name if deal.company else None,
                    deal.owner.full_name if deal.owner else None,
                    deal.expected_close_date,
                    deal.closed_at.isoformat() if deal.closed_at else None,
                    deal.created_at.isoformat(),
                ]
                for deal in deals
            ),
        )

    async def create(self, data: DealCreate, *, user: User) -> Deal:
        await self._check_references(data.model_dump())
        stage = await self._get_stage(data.stage_id) if data.stage_id else None
        stage = stage or await self.pipeline.get_default_stage()
        if stage is None:
            raise ConflictError("No pipeline stages are configured")

        deal = Deal(**data.model_dump(exclude={"stage_id"}))
        deal.currency = deal.currency.upper()
        deal.owner_id = data.owner_id or user.id
        deal.stage_id = stage.id
        deal.closed_at = utc_now() if stage.is_won or stage.is_lost else None
        await self.repo.add(deal)
        await self.session.commit()

        deal = await self.get(deal.id)
        events.publish(Event.DEAL_CREATED, _payload(deal))
        return deal

    async def update(self, deal_id: uuid.UUID, data: DealUpdate) -> Deal:
        deal = await self.get(deal_id)
        changes = data.model_dump(exclude_unset=True)
        new_stage_id = changes.pop("stage_id", None)
        await self._check_references(changes)

        if "currency" in changes:
            changes["currency"] = changes["currency"].upper()
        for field, value in changes.items():
            setattr(deal, field, value)

        previous_stage = None
        if new_stage_id is not None and new_stage_id != deal.stage_id:
            previous_stage = deal.stage
            new_stage = await self._get_stage(new_stage_id)
            deal.stage_id = new_stage.id
            deal.closed_at = utc_now() if new_stage.is_won or new_stage.is_lost else None

        await self.session.commit()
        deal = await self.get(deal_id)
        if previous_stage is not None:
            self._publish_stage_events(deal, previous_stage)
        return deal

    async def change_stage(self, deal_id: uuid.UUID, stage_id: uuid.UUID) -> Deal:
        """Move a deal to another stage; emits deal.stage_changed (+ deal.won / deal.lost)."""
        return await self.update(deal_id, DealUpdate(stage_id=stage_id))

    async def delete(self, deal_id: uuid.UUID) -> None:
        deal = await self.get(deal_id)
        await self.repo.delete(deal)
        await self.session.commit()

    def _publish_stage_events(self, deal: Deal, previous_stage: PipelineStage) -> None:
        payload = _payload(deal)
        previous = StageRef.model_validate(previous_stage).model_dump(mode="json")
        events.publish(Event.DEAL_STAGE_CHANGED, {**payload, "previous_stage": previous})
        if deal.stage.is_won:
            events.publish(Event.DEAL_WON, payload)
        elif deal.stage.is_lost:
            events.publish(Event.DEAL_LOST, payload)

    async def _get_stage(self, stage_id: uuid.UUID) -> PipelineStage:
        stage = await self.pipeline.get_stage(stage_id)
        if stage is None:
            raise NotFoundError("Pipeline stage not found")
        return stage

    async def _check_references(self, values: dict) -> None:
        if values.get("contact_id") and not await self.contacts.exists(values["contact_id"]):
            raise NotFoundError("Contact not found")
        if values.get("company_id") and not await self.companies.exists(values["company_id"]):
            raise NotFoundError("Company not found")
        if values.get("owner_id") and await self.users.get(values["owner_id"]) is None:
            raise NotFoundError("Owner not found")


def _payload(deal: Deal) -> dict:
    return DealRead.model_validate(deal).model_dump(mode="json")
