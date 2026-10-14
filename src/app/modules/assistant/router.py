"""The assistant: saved conversations with an AI that can read and change CRM data as you."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.email import MailerDep
from app.modules.assistant.dependencies import AIClientDep, ConversationServiceDep
from app.modules.assistant.schemas import (
    BulkAction,
    BulkResult,
    ChatTurn,
    ConversationDetail,
    ConversationFilters,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
)
from app.modules.auth.dependencies import CurrentUser
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/assistant/conversations", tags=["assistant"])


@router.get("", response_model=Page[ConversationRead])
async def list_conversations(
    service: ConversationServiceDep,
    user: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[ConversationFilters, Query()],
):
    """Your conversations, newest first. Admins can pass `scope=all` (and `user_id`)."""
    return await service.list_page(filters, params, user=user)


@router.post("", response_model=ChatTurn, status_code=status.HTTP_201_CREATED)
async def start_conversation(
    data: MessageCreate,
    service: ConversationServiceDep,
    user: CurrentUser,
    ai: AIClientDep,
    mailer: MailerDep,
):
    """Start a chat with its first message; the reply comes back in the same response.
    The assistant may create tasks, log activities, update records... (never deletes)."""
    return await service.start(data, user=user, ai=ai, mailer=mailer)


@router.post("/bulk", response_model=BulkResult)
async def bulk_update(data: BulkAction, service: ConversationServiceDep, user: CurrentUser):
    """Archive, restore or delete several conversations (admins: anyone's)."""
    return await service.bulk(data, user=user)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, service: ConversationServiceDep, user: CurrentUser
):
    return await service.get(conversation_id, user=user, with_messages=True)


@router.post("/{conversation_id}/messages", response_model=ChatTurn)
async def send_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    service: ConversationServiceDep,
    user: CurrentUser,
    ai: AIClientDep,
    mailer: MailerDep,
):
    return await service.send(conversation_id, data, user=user, ai=ai, mailer=mailer)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
    service: ConversationServiceDep,
    user: CurrentUser,
):
    """Rename or archive / unarchive."""
    return await service.update(conversation_id, data, user=user)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, service: ConversationServiceDep, user: CurrentUser
):
    await service.delete(conversation_id, user=user)
