import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.shared.schemas import ORMModel, UserRef

EntityType = Literal["contact", "company", "deal", "task", "activity"]


class AssistantAction(BaseModel):
    """Something the assistant changed in the CRM (shown as a link under its reply)."""

    kind: Literal["created", "updated", "completed", "logged", "moved", "sent", "scored"]
    entity: EntityType
    entity_id: uuid.UUID
    label: str
    # Where to look at it: the record itself, or the contact/deal a task or activity belongs to.
    link_entity: EntityType | None = None
    link_id: uuid.UUID | None = None


class AssistantReply(BaseModel):
    reply: str
    actions: list[AssistantAction]


class PageContext(BaseModel):
    """The record the user is looking at, so "this contact" / "this deal" work."""

    type: Literal["contact", "company", "deal"]
    id: uuid.UUID


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    context: PageContext | None = None


MAX_ATTACHMENTS = 3


class AttachedFile(BaseModel):
    """A file sent with a message: its name, and the text read from it (for the model)."""

    name: str
    text: str


class MessageWithFiles(MessageCreate):
    """The multipart variant (built by the router): the text is optional when files come along."""

    content: str = Field(default="", max_length=4000)
    attachments: list[AttachedFile] = Field(min_length=1, max_length=MAX_ATTACHMENTS)


class Transcript(BaseModel):
    """What was said in a voice recording. Empty when no speech was recognized."""

    text: str


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_archived: bool | None = None


class ConversationFilters(BaseModel):
    search: str | None = None
    archived: bool = False
    # "mine" (default) or, for admins, "all" users' conversations (optionally one user's).
    scope: Literal["mine", "all"] = "mine"
    user_id: uuid.UUID | None = None


class BulkAction(BaseModel):
    """Admin tool: archive, restore or delete many conversations at once."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["archive", "unarchive", "delete"]


class AttachmentRead(BaseModel):
    name: str


class MessageRead(ORMModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    actions: list[AssistantAction]
    attachments: list[AttachmentRead]  # file names only; their text is kept for the model
    created_at: datetime


class ConversationRead(ORMModel):
    id: uuid.UUID
    title: str
    is_archived: bool
    message_count: int
    last_message_at: datetime
    user_id: uuid.UUID
    user: UserRef
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class ChatTurn(BaseModel):
    """Result of sending a message: the updated conversation and the two new messages."""

    conversation: ConversationRead
    messages: list[MessageRead]


class BulkResult(BaseModel):
    affected: int
