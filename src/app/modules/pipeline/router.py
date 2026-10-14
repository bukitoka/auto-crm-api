from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.pipeline.dependencies import PipelineServiceDep
from app.modules.pipeline.schemas import StageRead

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/stages", response_model=list[StageRead])
async def list_stages(service: PipelineServiceDep, _: CurrentUser):
    return await service.list_stages()
