from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.pipeline.service import PipelineService


def get_pipeline_service(session: SessionDep) -> PipelineService:
    return PipelineService(session)


PipelineServiceDep = Annotated[PipelineService, Depends(get_pipeline_service)]
