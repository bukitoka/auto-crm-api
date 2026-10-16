import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import AdminUser, CurrentUser
from app.modules.pipeline.dependencies import PipelineServiceDep
from app.modules.pipeline.schemas import StageCreate, StageOrder, StageRead, StageUpdate

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/stages", response_model=list[StageRead])
async def list_stages(service: PipelineServiceDep, _: CurrentUser):
    return await service.list_stages()


@router.post("/stages", response_model=StageRead, status_code=status.HTTP_201_CREATED)
async def create_stage(data: StageCreate, service: PipelineServiceDep, _: AdminUser):
    return await service.create(data)


@router.put("/stages/order", response_model=list[StageRead])
async def reorder_stages(data: StageOrder, service: PipelineServiceDep, _: AdminUser):
    return await service.reorder(data)


@router.patch("/stages/{stage_id}", response_model=StageRead)
async def update_stage(
    stage_id: uuid.UUID, data: StageUpdate, service: PipelineServiceDep, _: AdminUser
):
    return await service.update(stage_id, data)


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage(
    stage_id: uuid.UUID,
    service: PipelineServiceDep,
    _: AdminUser,
    move_to: uuid.UUID | None = None,
):
    """Deals in the stage are moved to `move_to` first (required when there are any)."""
    await service.delete(stage_id, move_to=move_to)
