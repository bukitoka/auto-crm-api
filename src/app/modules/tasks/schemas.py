import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.tasks.models import TaskPriority, TaskStatus
from app.shared.schemas import ContactRef, DealRef, ORMModel, UserRef, reject_null


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.TODO
    assignee_id: uuid.UUID | None = None  # defaults to the current user
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_date: date | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    assignee_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None

    _not_null = field_validator("title", "priority", "status")(reject_null)


class TaskFilters(BaseModel):
    search: str | None = None
    status: TaskStatus | None = None
    assignee_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    overdue: bool | None = None  # true: due before today and not done


class TaskRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None
    due_date: date | None
    priority: TaskPriority
    status: TaskStatus
    completed_at: datetime | None
    assignee_id: uuid.UUID | None
    assignee: UserRef | None
    contact_id: uuid.UUID | None
    contact: ContactRef | None
    deal_id: uuid.UUID | None
    deal: DealRef | None
    created_by_id: uuid.UUID | None
    created_by: UserRef | None
    created_at: datetime
    updated_at: datetime
