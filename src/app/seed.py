"""Fill the database with realistic demo data.

Run with:  uv run seed            (refuses if the database already has CRM data)
           uv run seed --reset    (empties the CRM tables first, then seeds)

Records are created through the services, so the normal business rules and defaults
apply (first user is admin, deal closed_at, task completed_at, ...). No event handlers
are subscribed outside the web app, so no webhooks are called.
Faker and `random` use a fixed seed: every run produces the same names and amounts.
The pipeline stages come from the migrations and are left untouched.
"""

import argparse
import asyncio
import random
import re
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from faker import Faker
from pydantic import AnyHttpUrl
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionFactory, engine
from app.core.events import Event
from app.modules.activities.models import ActivityType
from app.modules.activities.schemas import ActivityCreate
from app.modules.activities.service import ActivityService
from app.modules.companies.models import Company
from app.modules.companies.schemas import CompanyCreate
from app.modules.companies.service import CompanyService
from app.modules.contacts.models import Contact, ContactStatus
from app.modules.contacts.schemas import ContactCreate
from app.modules.contacts.service import ContactService
from app.modules.deals.models import Deal
from app.modules.deals.schemas import DealCreate
from app.modules.deals.service import DealService
from app.modules.pipeline.models import PipelineStage
from app.modules.pipeline.repository import PipelineRepository
from app.modules.tasks.models import TaskPriority, TaskStatus
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import TaskService
from app.modules.users.models import User
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL, UserService
from app.modules.webhooks.schemas import WebhookCreate
from app.modules.webhooks.service import WebhookService
from app.shared.utils import today_utc, utc_now

RANDOM_SEED = 42

ADMIN = ("admin@example.com", "admin12345", "Alex Admin")
MEMBERS = [
    ("sarah@example.com", "member12345", "Sarah Chen"),
    ("marco@example.com", "member12345", "Marco Rossi"),
    ("priya@example.com", "member12345", "Priya Patel"),
]

COMPANY_COUNT = 10
CONTACT_COUNT = 40
DEAL_COUNT = 25
ACTIVITY_COUNT = 60
TASK_COUNT = 30

# The same tables the test suite cleans: everything except pipeline_stages and alembic_version.
CRM_TABLES = (
    "assistant_messages, assistant_conversations, activities, tasks, deals, contacts, "
    "companies, webhook_subscriptions, users"
)

N8N_WEBHOOKS = [
    (Event.CONTACT_CREATED, "http://localhost:5678/webhook/auto-crm/contact-created"),
    (Event.DEAL_WON, "http://localhost:5678/webhook/auto-crm/deal-won"),
]

INDUSTRIES = ["Software", "Retail", "Healthcare", "Finance", "Manufacturing", "Logistics"]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
SOURCES = ["manual", "web_form", "referral", "linkedin", "event", "import"]
TAGS = ["vip", "newsletter", "decision-maker", "technical", "budget-approved", "follow-up"]
DEAL_PRODUCTS = [
    "Annual license",
    "Onboarding package",
    "Enterprise upgrade",
    "Support renewal",
    "Pilot project",
    "Data migration",
]
ACTIVITY_SUBJECTS = {
    ActivityType.NOTE: ["Internal note", "Budget details", "Org chart notes"],
    ActivityType.CALL: ["Discovery call", "Follow-up call", "Pricing call"],
    ActivityType.EMAIL: ["Sent proposal", "Sent case study", "Replied to questions"],
    ActivityType.MEETING: ["Product demo", "Kick-off meeting", "Quarterly review"],
}
TASK_TITLES = [
    "Send proposal",
    "Schedule demo",
    "Follow up on pricing",
    "Prepare contract",
    "Check in after trial",
    "Book quarterly review",
]


@dataclass
class SeedSummary:
    users: int
    companies: int
    contacts: int
    deals: int
    activities: int
    tasks: int
    webhooks: int


class Seeder:
    """Creates the demo data in dependency order (users -> companies -> contacts -> ...)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.fake = Faker()
        self.fake.seed_instance(RANDOM_SEED)
        self.rng = random.Random(RANDOM_SEED)

    async def run(self) -> SeedSummary:
        users = await self._create_users()
        companies = await self._create_companies(users)
        contacts = await self._create_contacts(users, companies)
        deals = await self._create_deals(users, companies, contacts)
        activity_count = await self._create_activities(users, contacts, deals)
        task_count = await self._create_tasks(users, contacts, deals)
        webhook_count = await self._create_webhooks()
        await self._spread_dates(contacts, deals)
        return SeedSummary(
            users=len(users),
            companies=len(companies),
            contacts=len(contacts),
            deals=len(deals),
            activities=activity_count,
            tasks=task_count,
            webhooks=webhook_count,
        )

    async def _create_users(self) -> list[User]:
        service = UserService(self.session)
        users = []
        for email, password, full_name in [ADMIN, *MEMBERS]:
            # The first user created becomes the admin (business rule in UserService).
            users.append(await service.create(email=email, password=password, full_name=full_name))
        return users

    async def _create_companies(self, users: list[User]) -> list[Company]:
        service = CompanyService(self.session)
        companies = []
        for _ in range(COMPANY_COUNT):
            name = self.fake.unique.company()
            domain = _slug(name) + ".com"
            data = CompanyCreate(
                name=name,
                domain=domain,
                industry=self.rng.choice(INDUSTRIES),
                size=self.rng.choice(COMPANY_SIZES),
                website=f"https://{domain}",
                notes=self.fake.catch_phrase(),
                owner_id=self.rng.choice(users).id,
            )
            companies.append(await service.create(data, user=users[0]))
        return companies

    async def _create_contacts(self, users: list[User], companies: list[Company]) -> list[Contact]:
        service = ContactService(self.session)
        statuses = list(ContactStatus)
        contacts = []
        for index in range(CONTACT_COUNT):
            first_name = self.fake.first_name()
            last_name = self.fake.last_name()
            # Every 8th contact has no company (e.g. a freelancer).
            company = None if index % 8 == 7 else self.rng.choice(companies)
            domain = company.domain if company else "gmail.com"
            data = ContactCreate(
                first_name=first_name,
                last_name=last_name,
                email=f"{_slug(first_name)}.{_slug(last_name)}{index}@{domain}",
                phone=self.fake.phone_number()[:50],
                job_title=self.fake.job()[:150],
                status=statuses[index % len(statuses)],  # every status is used
                source=SOURCES[index % len(SOURCES)],
                tags=self.rng.sample(TAGS, k=self.rng.randint(0, 3)),
                company_id=company.id if company else None,
                owner_id=self.rng.choice(users).id,
            )
            contacts.append(await service.create(data, user=users[0]))
        return contacts

    async def _create_deals(
        self, users: list[User], companies: list[Company], contacts: list[Contact]
    ) -> list[Deal]:
        service = DealService(self.session)
        stages = await PipelineRepository(self.session).list_stages()
        company_names = {company.id: company.name for company in companies}
        # Deals go to contacts that work at a company: (contact, company name) pairs.
        candidates = [
            (contact, company_names[contact.company_id])
            for contact in contacts
            if contact.company_id is not None
        ]
        deals = []
        for index in range(DEAL_COUNT):
            stage = stages[index % len(stages)]  # every stage gets deals, Won/Lost included
            contact, company_name = self.rng.choice(candidates)
            data = DealCreate(
                title=f"{company_name} - {self.rng.choice(DEAL_PRODUCTS)}",
                value=Decimal(self.rng.randrange(1_000, 80_000, 500)),
                stage_id=stage.id,
                contact_id=contact.id,
                company_id=contact.company_id,
                owner_id=self.rng.choice(users).id,
                expected_close_date=today_utc() + timedelta(days=self.rng.randint(7, 90)),
            )
            deals.append(await service.create(data, user=users[0]))
        return deals

    async def _create_activities(
        self, users: list[User], contacts: list[Contact], deals: list[Deal]
    ) -> int:
        service = ActivityService(self.session)
        types = list(ActivityType)
        for index in range(ACTIVITY_COUNT):
            activity_type = types[index % len(types)]
            # Half of the activities belong to a deal (and its contact), half to a contact only.
            if index % 2 == 0:
                deal = self.rng.choice(deals)
                contact_id, deal_id = deal.contact_id, deal.id
            else:
                contact_id, deal_id = self.rng.choice(contacts).id, None
            data = ActivityCreate(
                type=activity_type,
                subject=self.rng.choice(ACTIVITY_SUBJECTS[activity_type]),
                body=self.fake.paragraph(nb_sentences=3),
                occurred_at=utc_now() - timedelta(days=self.rng.randint(0, 60), hours=index),
                contact_id=contact_id,
                deal_id=deal_id,
            )
            # The service sets created_by from the acting user.
            await service.create(data, user=self.rng.choice(users))
        return ACTIVITY_COUNT

    async def _create_tasks(
        self, users: list[User], contacts: list[Contact], deals: list[Deal]
    ) -> int:
        service = TaskService(self.session)
        priorities = list(TaskPriority)
        for index in range(TASK_COUNT):
            # A fixed mix: 6 overdue, 8 done, the rest open and due soon (or without a date).
            if index < 6:
                status, due_in_days = TaskStatus.TODO, -self.rng.randint(1, 14)
            elif index < 14:
                status, due_in_days = TaskStatus.DONE, -self.rng.randint(0, 20)
            else:
                status = self.rng.choice([TaskStatus.TODO, TaskStatus.IN_PROGRESS])
                due_in_days = self.rng.randint(0, 21)
            due_date = today_utc() + timedelta(days=due_in_days) if index % 10 != 9 else None
            deal = self.rng.choice(deals) if index % 3 == 0 else None
            contact_id = deal.contact_id if deal else self.rng.choice(contacts).id
            data = TaskCreate(
                title=self.rng.choice(TASK_TITLES),
                description=self.fake.sentence(),
                due_date=due_date,
                priority=priorities[index % len(priorities)],
                status=status,
                assignee_id=users[index % len(users)].id,  # everyone, the admin included
                contact_id=contact_id,
                deal_id=deal.id if deal else None,
            )
            await service.create(data, user=self.rng.choice(users))
        return TASK_COUNT

    async def _create_webhooks(self) -> int:
        """The n8n starter workflows' URLs, inactive until n8n is set up."""
        service = WebhookService(self.session)
        for event, url in N8N_WEBHOOKS:
            data = WebhookCreate(event=event, target_url=AnyHttpUrl(url), is_active=False)
            await service.create(data)
        return len(N8N_WEBHOOKS)

    async def _spread_dates(self, contacts: list[Contact], deals: list[Deal]) -> None:
        """Backdate records over the last ~4 months so the dashboard looks lived-in.

        The services always stamp "now"; this is the only place that writes dates directly.
        """
        now = utc_now()
        for contact in contacts:
            contact.created_at = now - timedelta(days=self.rng.randint(0, 120))
        for deal in deals:
            deal.created_at = now - timedelta(days=self.rng.randint(5, 120))
            if deal.closed_at is not None:
                age_in_days = (now - deal.created_at).days
                deal.closed_at = deal.created_at + timedelta(days=self.rng.randint(1, age_in_days))
        await self.session.commit()


async def has_crm_data(session: AsyncSession) -> bool:
    """True if any user (other than the service account) or company exists."""
    users = await session.scalar(
        select(func.count()).select_from(User).where(User.email != SERVICE_ACCOUNT_EMAIL)
    )
    companies = await session.scalar(select(func.count()).select_from(Company))
    return bool(users or companies)


async def reset_crm_tables(session: AsyncSession) -> None:
    await session.execute(text(f"TRUNCATE {CRM_TABLES} CASCADE"))
    await session.commit()


async def has_pipeline_stages(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(PipelineStage)))


async def seed(*, reset: bool) -> int:
    """Seed the configured database. Returns a process exit code."""
    async with SessionFactory() as session:
        if not await has_pipeline_stages(session):
            print("No pipeline stages found. Run `uv run alembic upgrade head` first.")
            return 1
        if await has_crm_data(session):
            if not reset:
                print("The database already has data. Use --reset to wipe it and seed again.")
                return 1
            print("Emptying the CRM tables (pipeline stages are kept)...")
            await reset_crm_tables(session)

        summary = await Seeder(session).run()

    print(
        f"Created {summary.users} users, {summary.companies} companies, "
        f"{summary.contacts} contacts, {summary.deals} deals, {summary.activities} activities, "
        f"{summary.tasks} tasks and {summary.webhooks} webhook subscriptions (inactive)."
    )
    print("\nLog in with:")
    for email, password, _ in [ADMIN, *MEMBERS]:
        role = "admin " if email == ADMIN[0] else "member"
        print(f"  {role}  {email}  /  {password}")
    return 0


def is_protected_database(name: str | None) -> bool:
    """Test and e2e databases are recreated by their tooling; never seed them by accident."""
    return name is not None and name.endswith(("_test", "_e2e"))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


async def _seed_and_close(reset: bool) -> int:
    try:
        return await seed(reset=reset)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill the database with demo data.")
    parser.add_argument(
        "--reset", action="store_true", help="empty the CRM tables first (keeps pipeline stages)"
    )
    args = parser.parse_args()

    url = make_url(settings.database_url)
    print(f"Target database: {url.database} on {url.host}:{url.port or 5432}")
    if is_protected_database(url.database):
        print("Refusing to seed a test/e2e database.")
        sys.exit(1)

    sys.exit(asyncio.run(_seed_and_close(args.reset)))


if __name__ == "__main__":
    main()
