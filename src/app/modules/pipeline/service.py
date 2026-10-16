import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import unscoped
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.modules.deals.service import DealService
from app.modules.pipeline.models import PipelineStage
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import StageCreate, StageOrder, StageRead, StageUpdate


class PipelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PipelineRepository(session)

    async def list_stages(self) -> list[StageRead]:
        counts = await self.repo.deal_counts()
        return [_read(stage, counts) for stage in await self.repo.list_stages()]

    async def create(self, data: StageCreate) -> StageRead:
        stages = await self.repo.list_stages()
        stage = PipelineStage(**data.model_dump(), position=0)
        _validate(stage, stages)

        # Open stages are inserted before the first won/lost stage; won/lost ones go last.
        index = len(stages)
        if not _is_closed(stage):
            index = next((i for i, s in enumerate(stages) if _is_closed(s)), len(stages))
        stages.insert(index, stage)
        for position, s in enumerate(stages, 1):
            s.position = position

        await self.repo.add(stage)
        await self.session.commit()
        return _read(stage, {})

    async def update(self, stage_id: uuid.UUID, data: StageUpdate) -> StageRead:
        stage = await self._get(stage_id)
        stages = await self.repo.list_stages()
        was_closed = _is_closed(stage)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(stage, field, value)
        _validate(stage, stages)
        if not was_closed and _is_closed(stage) and not _has_other_open_stage(stage, stages):
            raise BadRequestError("The pipeline needs at least one open stage")

        if _is_closed(stage) != was_closed:
            # Keep deals' closed_at in line with the stage, as moving a deal would.
            await self.repo.set_deals_closed(stage.id, closed=_is_closed(stage))
        await self.session.commit()
        return _read(stage, await self.repo.deal_counts())

    async def reorder(self, data: StageOrder) -> list[StageRead]:
        stages = {stage.id: stage for stage in await self.repo.list_stages()}
        if len(data.stage_ids) != len(stages) or set(data.stage_ids) != set(stages):
            raise BadRequestError("The new order must list every stage exactly once")
        for position, stage_id in enumerate(data.stage_ids, 1):
            stages[stage_id].position = position
        await self.session.commit()
        return await self.list_stages()

    async def delete(self, stage_id: uuid.UUID, *, move_to: uuid.UUID | None) -> None:
        """Delete a stage; its deals (if any) are first moved to `move_to`."""
        stage = await self._get(stage_id)
        if not _is_closed(stage) and not _has_other_open_stage(
            stage, await self.repo.list_stages()
        ):
            raise BadRequestError("The last open stage can't be deleted")

        deal_ids = await self.repo.deal_ids_in_stage(stage.id)
        if deal_ids:
            if move_to is None:
                raise ConflictError(
                    f"This stage has {len(deal_ids)} deal(s). Choose a stage to move them to."
                )
            if move_to == stage.id:
                raise BadRequestError("Deals can't be moved to the stage being deleted")
            await self._get(move_to)
            # One by one through DealService so closed_at and stage events behave as usual.
            deals = DealService(self.session)
            with unscoped(self.session):
                for deal_id in deal_ids:
                    await deals.change_stage(deal_id, move_to)

        await self.repo.delete(stage)
        await self.session.commit()

    async def _get(self, stage_id: uuid.UUID) -> PipelineStage:
        stage = await self.repo.get_stage(stage_id)
        if stage is None:
            raise NotFoundError("Pipeline stage not found")
        return stage


def _is_closed(stage: PipelineStage) -> bool:
    return stage.is_won or stage.is_lost


def _has_other_open_stage(stage: PipelineStage, stages: list[PipelineStage]) -> bool:
    return any(s is not stage and not _is_closed(s) for s in stages)


def _validate(stage: PipelineStage, stages: list[PipelineStage]) -> None:
    if stage.is_won and stage.is_lost:
        raise BadRequestError("A stage can't be both won and lost")
    name = stage.name.casefold()
    if any(s is not stage and s.name.casefold() == name for s in stages):
        raise ConflictError(f"A stage named '{stage.name}' already exists")


def _read(stage: PipelineStage, counts: dict[uuid.UUID, int]) -> StageRead:
    return StageRead.model_validate(stage).model_copy(
        update={"deal_count": counts.get(stage.id, 0)}
    )
