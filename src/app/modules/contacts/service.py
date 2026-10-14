import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.events import Event
from app.core.exceptions import ConflictError, NotFoundError
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
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams


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
        if values.get("owner_id") and await self.users.get(values["owner_id"]) is None:
            raise NotFoundError("Owner not found")


def _payload(contact: Contact) -> dict:
    return ContactRead.model_validate(contact).model_dump(mode="json")
