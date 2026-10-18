"""The assistant: saved conversations with an AI that can read and change CRM data as you."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.email import MailerDep
from app.core.exceptions import AppError, BadRequestError
from app.modules.ai.documents import read_upload_text
from app.modules.assistant.dependencies import AIClientDep, ConversationServiceDep
from app.modules.assistant.schemas import (
    MAX_ATTACHMENTS,
    AttachedFile,
    BulkAction,
    BulkResult,
    ChatTurn,
    ConversationDetail,
    ConversationFilters,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageWithFiles,
    PageContext,
)
from app.modules.auth.dependencies import CurrentUser
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/assistant/conversations", tags=["assistant"])


async def message_with_files(
    files: Annotated[list[UploadFile], File(description="Up to 3 files, 5 MB each")],
    content: Annotated[str, Form(max_length=4000)] = "",
    context_type: Annotated[Literal["contact", "company", "deal"] | None, Form()] = None,
    context_id: Annotated[uuid.UUID | None, Form()] = None,
) -> MessageWithFiles:
    """A message with attached files. DeepSeek only reads text, so each file is converted to
    text first, like smart capture does (OCR for images, PDF, Word, email, text)."""
    if len(files) > MAX_ATTACHMENTS:
        raise BadRequestError(f"Attach at most {MAX_ATTACHMENTS} files")
    attachments = []
    for file in files:
        name = file.filename or "file"
        try:
            attachments.append(AttachedFile(name=name, text=await read_upload_text(file)))
        except AppError as exc:
            raise type(exc)(f"{name}: {exc.message}") from exc
    context = PageContext(type=context_type, id=context_id) if context_type and context_id else None
    return MessageWithFiles(content=content.strip(), context=context, attachments=attachments)


MessageWithFilesDep = Annotated[MessageWithFiles, Depends(message_with_files)]


@router.get("", response_model=Page[ConversationRead])
async def list_conversations(
    service: ConversationServiceDep,
    user: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[ConversationFilters, Query()],
):
    """Your conversations, newest first. The super admin can pass `scope=all` (and `user_id`)."""
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


@router.post("/with-files", response_model=ChatTurn, status_code=status.HTTP_201_CREATED)
async def start_conversation_with_files(
    service: ConversationServiceDep,
    user: CurrentUser,
    ai: AIClientDep,
    mailer: MailerDep,
    data: MessageWithFilesDep,
):
    """Like `POST /`, as multipart: `content` (optional), `context_type` + `context_id`
    (optional) and up to 3 `files`."""
    return await service.start(data, user=user, ai=ai, mailer=mailer)


@router.post("/bulk", response_model=BulkResult)
async def bulk_update(data: BulkAction, service: ConversationServiceDep, user: CurrentUser):
    """Archive, restore or delete several of your conversations."""
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


@router.post("/{conversation_id}/messages/with-files", response_model=ChatTurn)
async def send_message_with_files(
    conversation_id: uuid.UUID,
    service: ConversationServiceDep,
    user: CurrentUser,
    ai: AIClientDep,
    mailer: MailerDep,
    data: MessageWithFilesDep,
):
    """Like `POST /{id}/messages`, as multipart with files (see `POST /with-files`)."""
    return await service.send(conversation_id, data, user=user, ai=ai, mailer=mailer)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
    service: ConversationServiceDep,
    user: CurrentUser,
):
    return await service.update(conversation_id, data, user=user)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, service: ConversationServiceDep, user: CurrentUser
):
    await service.delete(conversation_id, user=user)
