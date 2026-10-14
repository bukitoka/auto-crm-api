from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.modules.companies.schemas import CompanyCreate, CompanyFilters, CompanyUpdate
from app.modules.companies.service import CompanyService
from app.shared.pagination import PageParams
from tests.unit.conftest import make_company, make_user, mock_repos


@pytest.fixture
def service(session: AsyncMock) -> CompanyService:
    service = CompanyService(session)
    mock_repos(service, "repo", "users")
    return service


async def test_create_defaults_owner_to_current_user(service: CompanyService) -> None:
    user = make_user()
    service.repo.get.return_value = make_company()

    await service.create(CompanyCreate(name="Acme"), user=user)

    added = service.repo.add.call_args.args[0]
    assert added.name == "Acme"
    assert added.owner_id == user.id
    service.session.commit.assert_awaited_once()


async def test_create_keeps_an_explicit_owner(service: CompanyService) -> None:
    owner = make_user()
    service.users.get.return_value = owner
    service.repo.get.return_value = make_company()

    await service.create(CompanyCreate(name="Acme", owner_id=owner.id), user=make_user())

    assert service.repo.add.call_args.args[0].owner_id == owner.id


async def test_create_with_unknown_owner_is_not_found(service: CompanyService) -> None:
    service.users.get.return_value = None

    with pytest.raises(NotFoundError, match="Owner not found"):
        await service.create(CompanyCreate(name="Acme", owner_id=make_user().id), user=make_user())
    service.repo.add.assert_not_awaited()


async def test_get_unknown_company_is_not_found(service: CompanyService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Company not found"):
        await service.get(make_company().id)


async def test_update_changes_only_sent_fields(service: CompanyService) -> None:
    company = make_company(name="Old", industry="Retail", website="https://old.io")
    service.repo.get.return_value = company

    await service.update(company.id, CompanyUpdate(name="New", website=None))

    assert company.name == "New"
    assert company.website is None  # null clears an optional field
    assert company.industry == "Retail"  # not sent, unchanged


async def test_delete_removes_the_company(service: CompanyService) -> None:
    company = make_company()
    service.repo.get.return_value = company

    await service.delete(company.id)

    service.repo.delete.assert_awaited_once_with(company)
    service.session.commit.assert_awaited_once()


async def test_list_page_passes_filters_and_paging(service: CompanyService) -> None:
    service.repo.list_page.return_value = ([make_company()], 1)
    filters = CompanyFilters(industry="Software")

    page = await service.list_page(filters, PageParams(page=2, size=10))

    assert page.total == 1
    service.repo.list_page.assert_awaited_once_with(filters, offset=10, limit=10)
