import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.access import ensure_own
from app.core.events import Event
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.storage import Storage, get_storage
from app.modules.companies.repository import CompanyRepository
from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactFilters,
    ContactRead,
    ContactUpdate,
)
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.shared.csv_files import ImportResult, to_csv, validation_message
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams

# CSV columns: these map 1:1 to `ContactCreate` fields, the rest are handled below.
# Unknown columns are ignored on import, so an export can be imported again.
_PLAIN_FIELDS = ["first_name", "last_name", "email", "phone", "job_title", "status", "source"]
CSV_COLUMNS = [*_PLAIN_FIELDS, "tags", "company", "owner", "ai_score", "created_at"]


class ContactService:
    def __init__(self, session: AsyncSession, storage: Storage | None = None) -> None:
        self.session = session
        self.storage = storage or get_storage()
        self.repo = ContactRepository(session)
        self.companies = CompanyRepository(session)
        self.users = UserRepository(session)

    async def get(self, contact_id: uuid.UUID) -> Contact:
        contact = await self.repo.get(contact_id)
        if contact is None:
            raise NotFoundError("Contact not found")
        return contact

    async def list_page(self, filters: ContactFilters, params: PageParams) -> Page[ContactRead]:
        items, total = await self.repo.list_page(filters, offset=params.offset, limit=params.size)
        return Page[ContactRead].from_items(items, total, params)

    async def export_csv(self, filters: ContactFilters) -> str:
        contacts = await self.repo.list_all(filters)
        return to_csv(
            CSV_COLUMNS,
            (
                [
                    *(getattr(contact, field) for field in _PLAIN_FIELDS),
                    "; ".join(contact.tags),
                    contact.company.name if contact.company else None,
                    contact.owner.full_name if contact.owner else None,
                    contact.ai_score,
                    contact.created_at.isoformat(),
                ]
                for contact in contacts
            ),
        )

    async def import_csv(
        self, rows: list[tuple[int, dict[str, str]]], *, user: User
    ) -> ImportResult:
        """Create a contact per row; rows that are invalid or duplicate an email are skipped."""
        result = ImportResult()
        for number, row in rows:
            values: dict = {field: row[field] for field in _PLAIN_FIELDS if field in row}
            if "tags" in row:
                values["tags"] = [tag.strip() for tag in row["tags"].split(";") if tag.strip()]
            if "company" in row:  # unknown company names are left unlinked
                company = await self.companies.get_by_name(row["company"])
                values["company_id"] = company.id if company else None
            try:
                await self.create(ContactCreate.model_validate(values), user=user)
            except ValidationError as exc:
                result.skip(number, validation_message(exc))
            except AppError as exc:
                result.skip(number, exc.message)
            else:
                result.created += 1
        return result

    async def create(self, data: ContactCreate, *, user: User) -> Contact:
        values = data.model_dump()
        await self._validate(values)
        contact = Contact(**values)
        contact.owner_id = data.owner_id or user.id
        await self.repo.add(contact)
        await self.session.commit()

        contact = await self.get(contact.id)
        events.publish(Event.CONTACT_CREATED, _payload(contact))
        return contact

    async def update(self, contact_id: uuid.UUID, data: ContactUpdate) -> Contact:
        contact = await self.get(contact_id)
        changes = data.model_dump(exclude_unset=True)
        await self._validate(changes, current=contact)
        for field, value in changes.items():
            setattr(contact, field, value)
        await self.session.commit()

        contact = await self.get(contact.id)
        events.publish(Event.CONTACT_UPDATED, _payload(contact))
        return contact

    async def delete(self, contact_id: uuid.UUID) -> None:
        contact = await self.get(contact_id)
        await self.repo.delete(contact)
        await self.session.commit()
        if contact.avatar_key:
            await self.storage.delete(contact.avatar_key)

    async def set_avatar(self, contact_id: uuid.UUID, image: bytes) -> Contact:
        """Store a new photo (already converted by `read_image`) for the contact."""
        contact = await self.get(contact_id)
        contact.avatar_key = await replace_image(
            self.storage, folder=f"contacts/{contact.id}", image=image, old_key=contact.avatar_key
        )
        await self.session.commit()
        return await self.get(contact.id)

    async def remove_avatar(self, contact_id: uuid.UUID) -> Contact:
        contact = await self.get(contact_id)
        if contact.avatar_key:
            old_key, contact.avatar_key = contact.avatar_key, None
            await self.session.commit()
            await self.storage.delete(old_key)
        return await self.get(contact.id)

    async def _validate(self, values: dict, current: Contact | None = None) -> None:
        """Normalize email and check uniqueness and referenced rows (mutates `values`)."""
        if values.get("email"):
            values["email"] = values["email"].lower()
            existing = await self.repo.get_by_email(values["email"])
            if existing is not None and existing is not current:
                raise ConflictError("A contact with this email already exists")
        if values.get("company_id") and not await self.companies.exists(values["company_id"]):
            raise NotFoundError("Company not found")
        ensure_own(self.session, values.get("owner_id"))
        if values.get("owner_id") and await self.users.get(values["owner_id"]) is None:
            raise NotFoundError("Owner not found")


def _payload(contact: Contact) -> dict:
    return ContactRead.model_validate(contact).model_dump(mode="json")
