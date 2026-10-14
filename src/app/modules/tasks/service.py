import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.events import Event
from app.core.exceptions import NotFoundError
from app.modules.contacts.repository import ContactRepository
from app.modules.deals.repository import DealRepository
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskFilters, TaskRead, TaskUpdate
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.shared.pagination import Page, PageParams
from app.shared.utils import utc_now


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TaskRepository(session)
        self.users = UserRepository(session)
        self.contacts = ContactRepository(session)
        self.deals = DealRepository(session)

    async def get(self, task_id: uuid.UUID) -> Task:
        task = await self.repo.get(task_id)
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def list_page(self, filters: TaskFilters, params: PageParams) -> Page[TaskRead]:
        items, total = await self.repo.list_page(filters, offset=params.offset, limit=params.size)
        return Page[TaskRead].from_items(items, total, params)

    async def create(self, data: TaskCreate, *, user: User) -> Task:
        await self._check_references(data.model_dump())
        task = Task(**data.model_dump())
        task.assignee_id = data.assignee_id or user.id
        task.created_by_id = user.id
        if task.status == TaskStatus.DONE:
            task.completed_at = utc_now()
        await self.repo.add(task)
        await self.session.commit()

        task = await self.get(task.id)
        events.publish(Event.TASK_CREATED, _payload(task))
        return task

    async def update(self, task_id: uuid.UUID, data: TaskUpdate) -> Task:
        task = await self.get(task_id)
        changes = data.model_dump(exclude_unset=True)
        await self._check_references(changes)

        was_done = task.status == TaskStatus.DONE
        for field, value in changes.items():
            setattr(task, field, value)
        is_done = task.status == TaskStatus.DONE
        if is_done and not was_done:
            task.completed_at = utc_now()
        elif not is_done:
            task.completed_at = None
        await self.session.commit()

        task = await self.get(task_id)
        if is_done and not was_done:
            events.publish(Event.TASK_COMPLETED, _payload(task))
        return task

    async def delete(self, task_id: uuid.UUID) -> None:
        task = await self.get(task_id)
        await self.repo.delete(task)
        await self.session.commit()

    async def _check_references(self, values: dict) -> None:
        if values.get("assignee_id") and await self.users.get(values["assignee_id"]) is None:
            raise NotFoundError("Assignee not found")
        if values.get("contact_id") and not await self.contacts.exists(values["contact_id"]):
            raise NotFoundError("Contact not found")
        if values.get("deal_id") and not await self.deals.exists(values["deal_id"]):
            raise NotFoundError("Deal not found")


def _payload(task: Task) -> dict:
    return TaskRead.model_validate(task).model_dump(mode="json")
