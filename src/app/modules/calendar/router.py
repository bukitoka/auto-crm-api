import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self

from fastapi import APIRouter, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import select

from app.core.database import SessionDep
from app.core.exceptions import BadRequestError, NotFoundError
from app.modules.auth.dependencies import CurrentUser
from app.modules.calendar.models import CalendarEvent, EventColor
from app.modules.deals.models import Deal
from app.modules.tasks.models import Task, TaskStatus
from app.shared.record_links import RECORD_MODELS, RecordLinks, validate_link
from app.shared.schemas import ORMModel
from app.shared.utils import utc_now

router = APIRouter(prefix="/calendar/events", tags=["calendar"])


class EventInput(RecordLinks):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    color: EventColor = EventColor.TEAL
    notes: str | None = Field(default=None, max_length=4000)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("End time must be after start time")
        return self


class EventRead(ORMModel, EventInput):
    id: uuid.UUID
    owner_id: uuid.UUID


@router.get("", response_model=list[EventRead])
async def list_events(
    start: AwareDatetime, end: AwareDatetime, user: CurrentUser, session: SessionDep
):
    if not timedelta(0) < end - start <= timedelta(days=62):
        raise BadRequestError("Choose a calendar range of up to 62 days")
    return (
        await session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.owner_id == user.id,
                CalendarEvent.starts_at < end,
                CalendarEvent.ends_at > start,
            )
            .order_by(CalendarEvent.starts_at, CalendarEvent.id)
        )
    ).all()


class Deadline(BaseModel):
    id: uuid.UUID
    title: str
    day: date
    kind: Literal["task", "deal"]


async def deadlines_between(session: SessionDep, start: date, end: date) -> list[Deadline]:
    if not timedelta(0) < end - start <= timedelta(days=62):
        raise BadRequestError("Choose a calendar range of up to 62 days")
    tasks = await session.execute(
        select(Task.id, Task.title, Task.due_date).where(
            Task.status != TaskStatus.DONE, Task.due_date >= start, Task.due_date < end
        )
    )
    deals = await session.execute(
        select(Deal.id, Deal.title, Deal.expected_close_date).where(
            Deal.closed_at.is_(None),
            Deal.expected_close_date >= start,
            Deal.expected_close_date < end,
        )
    )
    return sorted(
        [
            Deadline(id=id, title=title, day=day, kind="task")
            for id, title, day in tasks
            if day is not None
        ]
        + [
            Deadline(id=id, title=title, day=day, kind="deal")
            for id, title, day in deals
            if day is not None
        ],
        key=lambda item: (item.day, item.title),
    )


schedule_router = APIRouter(prefix="/calendar", tags=["calendar"])


@schedule_router.get("/deadlines", response_model=list[Deadline])
async def calendar_deadlines(start: date, end: date, _: CurrentUser, session: SessionDep):
    return await deadlines_between(session, start, end)


def _require_future(value: datetime, now: datetime, label: str) -> None:
    if value <= now:
        raise BadRequestError(f"{label} time must be in the future")


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(data: EventInput, user: CurrentUser, session: SessionDep):
    _require_future(data.starts_at, utc_now(), "Start")
    await validate_link(session, data)
    event = CalendarEvent(owner_id=user.id, **data.model_dump())
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def get_owned_event(
    event_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> CalendarEvent:
    event = await session.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.owner_id == user.id)
    )
    if event is None:
        raise NotFoundError("Calendar event not found")
    return event


@router.get("/{event_id}", response_model=EventRead)
async def get_calendar_event(event_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    return await get_owned_event(event_id, user, session)


@router.put("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: uuid.UUID, data: EventInput, user: CurrentUser, session: SessionDep
):
    event = await get_owned_event(event_id, user, session)
    now = utc_now()
    if data.starts_at != event.starts_at:
        _require_future(data.starts_at, now, "Start")
    if data.ends_at != event.ends_at:
        _require_future(data.ends_at, now, "End")
    await validate_link(session, data)
    exclude = {"color"} - data.model_fields_set
    if not RECORD_MODELS.keys() & data.model_fields_set:
        exclude.update(RECORD_MODELS)
    for field, value in data.model_dump(exclude=exclude).items():
        setattr(event, field, value)
    await session.commit()
    await session.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    await session.delete(await get_owned_event(event_id, user, session))
    await session.commit()
