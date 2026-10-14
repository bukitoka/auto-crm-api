from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.ai.client import AIClient
from app.modules.ai.dependencies import get_ai_client
from app.modules.assistant.service import ConversationService


def get_conversation_service(session: SessionDep) -> ConversationService:
    return ConversationService(session)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
# Only the routes that talk to the model need it (503 when no DEEPSEEK_API_KEY is set);
# listing, renaming, archiving and deleting chats work without AI.
AIClientDep = Annotated[AIClient, Depends(get_ai_client)]
