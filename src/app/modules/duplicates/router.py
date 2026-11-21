import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update

from app.core.database import SessionDep
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.storage import StorageDep
from app.modules.activities.models import Activity
from app.modules.auth.dependencies import WorkingUser
from app.modules.calendar.models import CalendarEvent
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.documents.models import Document
from app.modules.tasks.models import Task

router = APIRouter(prefix="/duplicates", tags=["duplicates"])
Kind = Literal["contact", "company"]


class Candidate(BaseModel):
    id: uuid.UUID
    name: str
    details: list[str]


class DuplicateReview(BaseModel):
    keep: Candidate
    candidates: list[Candidate]


class MergeInput(BaseModel):
    keep_id: uuid.UUID
    duplicate_id: uuid.UUID


def _candidate(item: Contact | Company) -> Candidate:
    if isinstance(item, Contact):
        return Candidate(
            id=item.id,
            name=" ".join(filter(None, (item.first_name, item.last_name))),
            details=[value for value in (item.email, item.phone, item.job_title) if value],
        )
    return Candidate(
        id=item.id,
        name=item.name,
        details=[value for value in (item.domain, item.industry, item.website) if value],
    )


@router.get("/{kind}/{keep_id}", response_model=DuplicateReview)
async def find_duplicates(kind: Kind, keep_id: uuid.UUID, user: WorkingUser, session: SessionDep):
    model = Contact if kind == "contact" else Company
    keep = await session.scalar(select(model).where(model.id == keep_id, model.owner_id == user.id))
    if keep is None:
        raise NotFoundError("Record not found")
    if isinstance(keep, Contact):
        match = (func.lower(func.trim(Contact.first_name)) == keep.first_name.strip().lower()) & (
            func.lower(func.trim(func.coalesce(Contact.last_name, "")))
            == (keep.last_name or "").strip().lower()
        )
        if keep.phone:
            phone = func.regexp_replace(Contact.phone, "[^0-9]", "", "g")
            number = "".join(character for character in keep.phone if character.isdecimal())
            if len(number) >= 7:
                match = or_(match, phone == number)
    else:
        match = func.lower(func.trim(Company.name)) == keep.name.strip().lower()
        if keep.domain:
            match = or_(match, func.lower(func.trim(Company.domain)) == keep.domain.strip().lower())
    candidates = await session.scalars(
        select(model)
        .where(model.owner_id == user.id, model.id != keep_id, match)
        .order_by(model.created_at, model.id)
        .limit(25)
    )
    return DuplicateReview(
        keep=_candidate(keep), candidates=[_candidate(item) for item in candidates]
    )


@router.post("/{kind}/merge", response_model=Candidate)
async def merge_duplicates(
    kind: Kind, data: MergeInput, user: WorkingUser, session: SessionDep, storage: StorageDep
):
    if data.keep_id == data.duplicate_id:
        raise BadRequestError("Choose two different records")
    model = Contact if kind == "contact" else Company
    records = await session.scalars(
        select(model)
        .where(model.owner_id == user.id, model.id.in_([data.keep_id, data.duplicate_id]))
        .order_by(model.id)
        .with_for_update()
    )
    by_id = {record.id: record for record in records}
    keep = by_id.get(data.keep_id)
    source = by_id.get(data.duplicate_id)
    if keep is None or source is None:
        raise NotFoundError("Record not found")
    if isinstance(keep, Contact) and isinstance(source, Contact):
        field = "contact_id"
        related = (Activity, Task, Deal, CalendarEvent, Document)
        details = ("last_name", "email", "phone", "job_title", "company_id", "avatar_key")
        discarded_image = source.avatar_key if keep.avatar_key else None
        keep.tags = list(dict.fromkeys([*keep.tags, *source.tags]))
    elif isinstance(keep, Company) and isinstance(source, Company):
        field = "company_id"
        related = (Contact, Deal, CalendarEvent, Document)
        details = ("domain", "industry", "size", "website", "logo_key")
        discarded_image = source.logo_key if keep.logo_key else None
        if source.notes and source.notes != keep.notes:
            keep.notes = "\n\n".join(filter(None, (keep.notes, source.notes)))
    else:
        raise BadRequestError("Choose records of the same type")

    # Move relationships before deleting the source so its FK cascades cannot remove them.
    for relation in related:
        column = getattr(relation, field)
        await session.execute(update(relation).where(column == source.id).values({field: keep.id}))
    inherited = {key: getattr(source, key) for key in details if not getattr(keep, key)}
    await session.delete(source)
    await session.flush()
    # In particular, copying an email must wait for the source's unique value to be released.
    for key, value in inherited.items():
        setattr(keep, key, value)
    await session.commit()
    if discarded_image:
        await storage.delete(discarded_image)
    return _candidate(keep)
