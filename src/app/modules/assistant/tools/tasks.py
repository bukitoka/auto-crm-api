"""List and update tasks, and read or log CRM activities."""

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import NotFoundError
from app.modules.activities.models import ActivityType
from app.modules.activities.schemas import ActivityCreate, ActivityFilters
from app.modules.assistant.schemas import AssistantAction
from app.modules.assistant.tools.definitions import ToolContext
from app.modules.assistant.tools.results import (
    _activity_view,
    _link_for,
    _listing,
    _page,
    _task_view,
)
from app.modules.tasks.models import TaskPriority, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskFilters, TaskUpdate


class ListTasksParams(BaseModel):
    search: str | None = Field(default=None, description="Words in the task title")
    assignee: str = Field(
        default="all",
        description='"all" (everything you can see), "me" (the current user) '
        "or an admin's user id from list_users",
    )
    overdue_only: bool = False
    include_done: bool = False
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def list_tasks(ctx: ToolContext, params: ListTasksParams) -> dict[str, Any]:
    scope = params.assignee.strip().lower()
    if scope == "all":
        assignee_id = None
    elif scope == "me":
        assignee_id = ctx.user.id
    else:
        try:
            assignee_id = uuid.UUID(scope)
        except ValueError:
            raise NotFoundError('Unknown assignee. Use "all", "me" or a user id') from None
    filters = TaskFilters(
        search=params.search,
        assignee_id=assignee_id,
        overdue=True if params.overdue_only else None,
        open=None if params.include_done else True,
        contact_id=params.contact_id,
        deal_id=params.deal_id,
    )
    page = await ctx.tasks.list_page(filters, _page())
    return {"assignee": scope} | _listing("tasks", page, _task_view)


class CreateTaskParams(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: date | None = Field(default=None, description="YYYY-MM-DD")
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: uuid.UUID | None = Field(
        default=None, description="Your own user id; defaults to the current user"
    )
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def create_task(ctx: ToolContext, params: CreateTaskParams) -> dict[str, Any]:
    task = await ctx.tasks.create(TaskCreate(**params.model_dump()), user=ctx.user)
    due = f" (due {task.due_date:%b %-d})" if task.due_date else ""
    ctx.actions.append(
        AssistantAction(
            kind="created",
            entity="task",
            entity_id=task.id,
            label=f"Task: {task.title}{due}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"created_task": _task_view(task)}


class TaskIdParams(BaseModel):
    task_id: uuid.UUID


async def complete_task(ctx: ToolContext, params: TaskIdParams) -> dict[str, Any]:
    task = await ctx.tasks.update(params.task_id, TaskUpdate(status=TaskStatus.DONE))
    ctx.actions.append(
        AssistantAction(
            kind="completed",
            entity="task",
            entity_id=task.id,
            label=f"Completed: {task.title}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"completed_task": _task_view(task)}


class UpdateTaskParams(BaseModel):
    task_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = Field(default=None, description="New due date, YYYY-MM-DD")
    priority: TaskPriority | None = None
    description: str | None = None
    assignee_id: uuid.UUID | None = None


async def update_task(ctx: ToolContext, params: UpdateTaskParams) -> dict[str, Any]:
    changes = params.model_dump(exclude={"task_id"}, exclude_none=True)
    task = await ctx.tasks.update(params.task_id, TaskUpdate(**changes))
    ctx.actions.append(
        AssistantAction(
            kind="updated",
            entity="task",
            entity_id=task.id,
            label=f"Updated task: {task.title}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"updated_task": _task_view(task)}


class LogActivityParams(BaseModel):
    type: ActivityType = Field(description="note, call, email or meeting")
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def log_activity(ctx: ToolContext, params: LogActivityParams) -> dict[str, Any]:
    activity = await ctx.activities.create(ActivityCreate(**params.model_dump()), user=ctx.user)
    ctx.actions.append(
        AssistantAction(
            kind="logged",
            entity="activity",
            entity_id=activity.id,
            label=f"{activity.type.capitalize()}: {activity.subject}",
            **_link_for(activity.contact_id, activity.deal_id),
        )
    )
    return {"logged_activity": _activity_view(activity)}


class ActivityListParams(BaseModel):
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    type: ActivityType | None = None
    search: str | None = None


async def list_activities(ctx: ToolContext, params: ActivityListParams) -> dict[str, Any]:
    page = await ctx.activities.list_page(ActivityFilters(**params.model_dump()), _page())
    return _listing("activities", page, _activity_view)
