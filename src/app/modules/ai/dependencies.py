from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.core.database import SessionDep
from app.core.exceptions import ServiceUnavailableError
from app.modules.ai.client import AIClient
from app.modules.ai.service import AIService


@lru_cache
def _build_client(api_key: str, base_url: str, model: str) -> AIClient:
    return AIClient(api_key=api_key, base_url=base_url, model=model)


def get_ai_client() -> AIClient:
    """The configured AI client. Returns 503 when no API key is set."""
    if not settings.deepseek_api_key:
        raise ServiceUnavailableError(
            "AI features are disabled: set DEEPSEEK_API_KEY in the API's .env file"
        )
    return _build_client(
        settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model
    )


def get_ai_service(
    session: SessionDep, client: Annotated[AIClient, Depends(get_ai_client)]
) -> AIService:
    return AIService(session, client)


AIServiceDep = Annotated[AIService, Depends(get_ai_service)]
