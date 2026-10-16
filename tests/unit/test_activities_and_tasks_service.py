from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.events import Event
from app.core.exceptions import NotFoundError
from app.modules.activities import service as activity_service_module
from app.modules.activities.models import ActivityType
from app.modules.activities.schemas import ActivityCreate, ActivityFilters
from app.modules.activities.service import ActivityService
from app.modules.tasks import service as task_service_module
from app.modules.tasks.models import TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskFilters, TaskUpdate
from app.modules.tasks.service import TaskService
from app.shared.pagination import PageParams
from tests.unit.conftest import (
    event_names,
    make_activity,
    make_contact,
    make_deal,
    make_task,
    make_user,
    mock_repos,
)

Published = list[tuple[Event, dict[str, Any]]]
NOW = datetime(2026, 2, 1, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_service_module, "utc_now", lambda: NOW)
    monkeypatch.setattr(task_service_module, "utc_now", lambda: NOW)


@pytest.fixture
def activities(session: AsyncMock) -> ActivityService:
    service = ActivityService(session)
    mock_repos(service, "repo", "contacts", "deals")
    service.repo.get.return_value = make_activity()
    return service


async def test_activity_defaults_occurred_at_and_records_author(
    activities: ActivityService,
) -> None:
    user = make_user()
    contact = make_contact()

    await activities.create(
        ActivityCreate(type=ActivityType.NOTE, subject="Hi", contact_id=contact.id), user=user
    )

    added = activities.repo.add.call_args.args[0]
    assert added.occurred_at == NOW
    assert added.created_by_id == user.id
    assert added.contact_id == contact.id


async def test_activity_keeps_an_explicit_occurred_at(activities: ActivityService) -> None:
    when = datetime(2025, 12, 24, 10, 0, tzinfo=UTC)

    await activities.create(
        ActivityCreate(
            type=ActivityType.CALL, subject="Call", deal_id=make_deal().id, occurred_at=when
        ),
        user=make_user(),
    )

    assert activities.repo.add.call_args.args[0].occurred_at == when


@pytest.mark.parametrize(
    ("field", "repo", "message"),
    [("contact_id", "contacts", "Contact not found"), ("deal_id", "deals", "Deal not found")],
)
async def test_activity_with_unknown_target_is_not_found(
    activities: ActivityService, field: str, repo: str, message: str
) -> None:
    getattr(activities, repo).exists.return_value = False
    data = ActivityCreate.model_validate({"type": "email", "subject": "Hi", field: make_user().id})

    with pytest.raises(NotFoundError, match=message):
        await activities.create(data, user=make_user())
    activities.repo.add.assert_not_awaited()


async def test_get_unknown_activity_is_not_found(activities: ActivityService) -> None:
    activities.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Activity not found"):
        await activities.get(make_activity().id)


async def test_delete_activity(activities: ActivityService) -> None:
    activity = make_activity()
    activities.repo.get.return_value = activity

    await activities.delete(activity.id)

    activities.repo.delete.assert_awaited_once_with(activity)


async def test_list_activities(activities: ActivityService) -> None:
    activities.repo.list_page.return_value = ([make_activity()], 1)

    page = await activities.list_page(ActivityFilters(type=ActivityType.CALL), PageParams())

    assert page.items[0].type == ActivityType.CALL


@pytest.fixture
def tasks(session: AsyncMock) -> TaskService:
    service = TaskService(session)
    mock_repos(service, "repo", "users", "contacts", "deals")
    return service


async def test_task_defaults_assignee_to_creator_and_emits_task_created(
    tasks: TaskService, published_events: Published
) -> None:
    user = make_user()
    tasks.repo.get.return_value = make_task()

    await tasks.create(TaskCreate(title="Call back"), user=user)

    added = tasks.repo.add.call_args.args[0]
    assert added.assignee_id == user.id
    assert added.created_by_id == user.id
    assert added.completed_at is None
    assert event_names(published_events) == [Event.TASK_CREATED]


async def test_task_created_as_done_gets_completed_at(
    tasks: TaskService, published_events: Published
) -> None:
    tasks.repo.get.return_value = make_task(status=TaskStatus.DONE, completed_at=NOW)

    await tasks.create(TaskCreate(title="Already done", status=TaskStatus.DONE), user=make_user())

    assert tasks.repo.add.call_args.args[0].completed_at == NOW


async def test_completing_a_task_sets_completed_at_and_emits_task_completed(
    tasks: TaskService, published_events: Published
) -> None:
    task = make_task(status=TaskStatus.IN_PROGRESS)
    tasks.repo.get.return_value = task

    await tasks.update(task.id, TaskUpdate(status=TaskStatus.DONE))

    assert task.completed_at == NOW
    assert event_names(published_events) == [Event.TASK_COMPLETED]
    assert published_events[0][1]["status"] == "done"


async def test_editing_a_done_task_keeps_completed_at_and_emits_nothing(
    tasks: TaskService, published_events: Published
) -> None:
    completed_at = datetime(2026, 1, 1, tzinfo=UTC)
    task = make_task(status=TaskStatus.DONE, completed_at=completed_at)
    tasks.repo.get.return_value = task

    await tasks.update(task.id, TaskUpdate(title="Renamed"))

    assert task.completed_at == completed_at
    assert published_events == []


async def test_reopening_a_task_clears_completed_at(
    tasks: TaskService, published_events: Published
) -> None:
    task = make_task(status=TaskStatus.DONE, completed_at=NOW)
    tasks.repo.get.return_value = task

    await tasks.update(task.id, TaskUpdate(status=TaskStatus.TODO, due_date=date(2026, 3, 1)))

    assert task.completed_at is None
    assert task.due_date == date(2026, 3, 1)
    assert published_events == []


@pytest.mark.parametrize(
    ("field", "repo", "message"),
    [
        ("assignee_id", "users", "Assignee not found"),
        ("contact_id", "contacts", "Contact not found"),
        ("deal_id", "deals", "Deal not found"),
    ],
)
async def test_task_with_unknown_reference_is_not_found(
    tasks: TaskService, field: str, repo: str, message: str
) -> None:
    getattr(tasks, repo).get.return_value = None
    getattr(tasks, repo).exists.return_value = False

    with pytest.raises(NotFoundError, match=message):
        await tasks.create(
            TaskCreate.model_validate({"title": "T", field: make_user().id}), user=make_user()
        )


async def test_get_unknown_task_is_not_found(tasks: TaskService) -> None:
    tasks.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Task not found"):
        await tasks.get(make_task().id)


async def test_delete_task(tasks: TaskService) -> None:
    task = make_task()
    tasks.repo.get.return_value = task

    await tasks.delete(task.id)

    tasks.repo.delete.assert_awaited_once_with(task)


async def test_list_tasks_passes_the_overdue_filter(tasks: TaskService) -> None:
    tasks.repo.list_page.return_value = ([make_task()], 1)
    filters = TaskFilters(overdue=True)

    page = await tasks.list_page(filters, PageParams())

    assert page.total == 1
    tasks.repo.list_page.assert_awaited_once_with(filters, offset=0, limit=20)
