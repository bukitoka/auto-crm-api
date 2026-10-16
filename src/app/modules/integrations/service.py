import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activities.models import Activity, ActivityType
from app.modules.activities.repository import ActivityRepository
from app.modules.companies.models import Company
from app.modules.companies.repository import CompanyRepository
from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import ContactCreate
from app.modules.contacts.service import ContactService
from app.modules.integrations.schemas import LeadIntake
from app.modules.users.models import User


class IntegrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.contact_service = ContactService(session)
        self.contacts = ContactRepository(session)
        self.companies = CompanyRepository(session)
        self.activities = ActivityRepository(session)

    async def ingest_lead(self, data: LeadIntake, *, user: User) -> tuple[Contact, bool]:
        """Create a lead, or reuse the contact with the same email.

        Returns the contact and whether it was created. The optional message becomes a note.
        """
        contact = await self.contacts.get_by_email(data.email)
        created = contact is None

        if contact is None:
            company = await self._find_or_create_company(
                data.company_name, owner_id=data.owner_id, user=user
            )
            contact = await self.contact_service.create(
                ContactCreate(
                    first_name=data.first_name,
                    last_name=data.last_name,
                    email=data.email,
                    phone=data.phone,
                    source=data.source,
                    company_id=company.id if company else None,
                    owner_id=data.owner_id,
                ),
                user=user,
            )

        if data.message:
            note = Activity(
                type=ActivityType.NOTE,
                subject=f"Message via {data.source}",
                body=data.message,
                contact_id=contact.id,
                created_by_id=user.id,
            )
            await self.activities.add(note)
            await self.session.commit()

        return await self.contact_service.get(contact.id), created

    async def _find_or_create_company(
        self, name: str | None, *, owner_id: uuid.UUID | None, user: User
    ) -> Company | None:
        if not name:
            return None
        company = await self.companies.get_by_name(name)
        if company is None:
            company = await self.companies.add(Company(name=name, owner_id=owner_id or user.id))
        return company
