import uuid
from datetime import date
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from app.core.storage import get_storage
from app.modules.assistant.schemas import AssistantAction
from app.modules.assistant.tools.definitions import ToolContext
from app.modules.calendar.router import (
    EventInput,
    EventRead,
    create_event,
    deadlines_between,
    get_owned_event,
    list_events,
)
from app.modules.dashboard.follow_ups import list_follow_ups
from app.modules.documents.service import DocumentService
from app.modules.duplicates.router import Kind, find_duplicates
from app.shared.record_links import RecordLinks


class SearchDocuments(RecordLinks):
    search: str = Field(default="", max_length=200)


class ReadDocument(BaseModel):
    document_id: uuid.UUID


class DuplicateRecord(BaseModel):
    kind: Kind
    record_id: uuid.UUID


async def review_duplicates(ctx: ToolContext, params: DuplicateRecord) -> dict[str, Any]:
    result = await find_duplicates(params.kind, params.record_id, ctx.user, ctx.session)
    return result.model_dump(mode="json")


class EventId(BaseModel):
    event_id: uuid.UUID


async def get_calendar_event(ctx: ToolContext, params: EventId) -> dict[str, Any]:
    event = await get_owned_event(params.event_id, ctx.user, ctx.session)
    return EventRead.model_validate(event).model_dump(mode="json")


class ScheduleWindow(BaseModel):
    start: AwareDatetime
    end: AwareDatetime


class DeadlineWindow(BaseModel):
    start: date
    end: date


async def search_documents(ctx: ToolContext, params: SearchDocuments) -> dict[str, Any]:
    items = await DocumentService(ctx.session, ctx.user, get_storage()).list_documents(
        params, params.search
    )
    return {"documents": [item.model_dump(mode="json") for item in items]}


async def read_document(ctx: ToolContext, params: ReadDocument) -> dict[str, Any]:
    service = DocumentService(ctx.session, ctx.user, get_storage())
    item = await service.get(params.document_id)
    return {
        "filename": item.filename,
        "untrusted_file_text": await service.read_text(params.document_id),
    }


async def list_calendar_events(ctx: ToolContext, params: ScheduleWindow) -> dict[str, Any]:
    events = await list_events(params.start, params.end, ctx.user, ctx.session)
    return {"events": [EventRead.model_validate(event).model_dump(mode="json") for event in events]}


async def create_calendar_event(ctx: ToolContext, params: EventInput) -> dict[str, Any]:
    event = await create_event(params, ctx.user, ctx.session)
    ctx.actions.append(
        AssistantAction(
            kind="created", entity="calendar_event", entity_id=event.id, label=event.title
        )
    )
    return EventRead.model_validate(event).model_dump(mode="json")


async def list_calendar_deadlines(ctx: ToolContext, params: DeadlineWindow) -> dict[str, Any]:
    items = await deadlines_between(ctx.session, params.start, params.end)
    return {"deadlines": [item.model_dump(mode="json") for item in items]}


async def get_follow_ups(ctx: ToolContext, _: BaseModel) -> dict[str, Any]:
    items = await list_follow_ups(ctx.session)
    return {"follow_ups": [item.model_dump(mode="json") for item in items]}
