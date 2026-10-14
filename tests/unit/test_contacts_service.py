from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.events import Event
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.contacts.schemas import ContactCreate, ContactFilters, ContactUpdate
from app.modules.contacts.service import ContactService
from app.shared.pagination import PageParams
from tests.unit.conftest import event_names, make_company, make_contact, make_user, mock_repos

Published = list[tuple[Event, dict[str, Any]]]


@pytest.fixture
def service(session: AsyncMock) -> ContactService:
    service = ContactService(session)
    mock_repos(service, "repo", "companies", "users")
    service.repo.get_by_email.return_value = None
    return service


async def test_create_lowercases_email_and_defaults_owner(
    service: ContactService, published_events: Published
) -> None:
    user = make_user()
    service.repo.get.return_value = make_contact(email="jane@acme.com")

    await service.create(ContactCreate(first_name="Jane", email="Jane@ACME.com"), user=user)

    added = service.repo.add.call_args.args[0]
    assert added.email == "jane@acme.com"
    assert added.owner_id == user.id
    service.repo.get_by_email.assert_awaited_once_with("jane@acme.com")


async def test_create_publishes_contact_created(
    service: ContactService, published_events: Published
) -> None:
    saved = make_contact(first_name="Eve")
    service.repo.get.return_value = saved

    result = await service.create(ContactCreate(first_name="Eve"), user=make_user())

    assert result is saved
    assert event_names(published_events) == [Event.CONTACT_CREATED]
    assert published_events[0][1]["id"] == str(saved.id)


async def test_create_with_duplicate_email_conflicts(
    service: ContactService, published_events: Published
) -> None:
    service.repo.get_by_email.return_value = make_contact(email="sam@example.com")

    with pytest.raises(ConflictError, match="email already exists"):
        await service.create(
            ContactCreate(first_name="Sam", email="sam@example.com"), user=make_user()
        )
    service.repo.add.assert_not_awaited()
    assert published_events == []


async def test_create_with_unknown_company_is_not_found(service: ContactService) -> None:
    service.companies.exists.return_value = False

    with pytest.raises(NotFoundError, match="Company not found"):
        await service.create(
            ContactCreate(first_name="Jane", company_id=make_company().id), user=make_user()
        )


async def test_create_with_unknown_owner_is_not_found(service: ContactService) -> None:
    service.users.get.return_value = None

    with pytest.raises(NotFoundError, match="Owner not found"):
        await service.create(
            ContactCreate(first_name="Jane", owner_id=make_user().id), user=make_user()
        )


async def test_update_keeping_own_email_is_not_a_conflict(
    service: ContactService, published_events: Published
) -> None:
    contact = make_contact(email="jane@acme.com")
    service.repo.get.return_value = contact
    service.repo.get_by_email.return_value = contact  # the email belongs to this contact

    await service.update(contact.id, ContactUpdate(email="JANE@acme.com", job_title="CEO"))

    assert contact.email == "jane@acme.com"
    assert contact.job_title == "CEO"
    assert event_names(published_events) == [Event.CONTACT_UPDATED]


async def test_update_to_another_contacts_email_conflicts(service: ContactService) -> None:
    contact = make_contact(email="jane@acme.com")
    service.repo.get.return_value = contact
    service.repo.get_by_email.return_value = make_contact(email="john@acme.com")

    with pytest.raises(ConflictError):
        await service.update(contact.id, ContactUpdate(email="john@acme.com"))
    assert contact.email == "jane@acme.com"


async def test_update_can_clear_the_company(
    service: ContactService, published_events: Published
) -> None:
    company = make_company()
    contact = make_contact(company_id=company.id)
    service.repo.get.return_value = contact

    await service.update(contact.id, ContactUpdate(company_id=None))

    assert contact.company_id is None
    service.companies.exists.assert_not_awaited()


async def test_get_unknown_contact_is_not_found(service: ContactService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Contact not found"):
        await service.get(make_contact().id)


async def test_delete_removes_the_contact(service: ContactService) -> None:
    contact = make_contact()
    service.repo.get.return_value = contact

    await service.delete(contact.id)

    service.repo.delete.assert_awaited_once_with(contact)


async def test_list_page_passes_filters_and_paging(service: ContactService) -> None:
    service.repo.list_page.return_value = ([make_contact()], 1)
    filters = ContactFilters(search="jane", status="lead")

    page = await service.list_page(filters, PageParams())

    assert page.items[0].first_name == "Jane"
    service.repo.list_page.assert_awaited_once_with(filters, offset=0, limit=20)
