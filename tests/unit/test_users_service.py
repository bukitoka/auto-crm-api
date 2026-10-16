from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import verify_password
from app.modules.users.models import SERVICE_ACCOUNT_EMAIL, UserRole
from app.modules.users.schemas import AdminCreate, UserUpdate
from app.modules.users.service import UserService
from app.shared.pagination import PageParams
from tests.unit.conftest import make_user, mock_repos


@pytest.fixture
def service(session: AsyncMock) -> UserService:
    service = UserService(session)
    mock_repos(service, "repo")
    service.repo.get_by_email.return_value = None
    service.repo.super_admin_exists.return_value = True
    return service


async def test_create_admin_makes_a_plain_admin(service: UserService) -> None:
    data = AdminCreate(email="Next@Example.com", password="pw123456", full_name="Next")

    user = await service.create_admin(data)

    assert (user.email, user.role, user.is_super_admin) == (
        "next@example.com",
        UserRole.ADMIN,
        False,
    )
    assert verify_password("pw123456", user.hashed_password)
    service.session.commit.assert_awaited_once()


async def test_create_admin_with_existing_email_conflicts(service: UserService) -> None:
    service.repo.get_by_email.return_value = make_user()

    with pytest.raises(ConflictError, match="already exists"):
        await service.create_admin(
            AdminCreate(email="user@example.com", password="pw123456", full_name="Dup")
        )
    service.session.commit.assert_not_awaited()


async def test_setup_creates_the_super_admin_once(service: UserService) -> None:
    service.repo.super_admin_exists.return_value = False
    user = await service.setup(email="Root@Example.com", password="pw123456", full_name="Root")
    assert (user.email, user.is_super_admin) == ("root@example.com", True)

    service.repo.super_admin_exists.return_value = True
    with pytest.raises(ConflictError, match="already set up"):
        await service.setup(email="two@example.com", password="pw123456", full_name="Two")


async def test_set_password(service: UserService) -> None:
    user = make_user()
    service.repo.get_by_email.return_value = user

    await service.set_password(user.email, "new-password")

    assert verify_password("new-password", user.hashed_password)
    service.session.commit.assert_awaited_once()


@pytest.mark.parametrize("email", ["nobody@example.com", SERVICE_ACCOUNT_EMAIL])
async def test_set_password_unknown_or_service_account(service: UserService, email: str) -> None:
    service.repo.get_by_email.return_value = make_user(email=email) if "auto" in email else None

    with pytest.raises(NotFoundError, match="User not found"):
        await service.set_password(email, "new-password")


async def test_get_unknown_user_is_not_found(service: UserService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="User not found"):
        await service.get(make_user().id)


async def test_super_admin_lists_every_admin(service: UserService) -> None:
    service.repo.list_page.return_value = ([make_user()], 1)

    page = await service.list_page(
        PageParams(page=1, size=20), search="uma", viewer=make_user(is_super_admin=True)
    )

    assert page.total == 1
    service.repo.list_page.assert_awaited_once_with(search="uma", only_id=None, offset=0, limit=20)


async def test_admin_lists_only_themselves(service: UserService) -> None:
    admin = make_user()
    service.repo.list_page.return_value = ([admin], 1)

    await service.list_page(PageParams(page=1, size=20), search=None, viewer=admin)

    service.repo.list_page.assert_awaited_once_with(
        search=None, only_id=admin.id, offset=0, limit=20
    )


async def test_update_deactivates_and_renames(service: UserService) -> None:
    admin = make_user()
    service.repo.get.return_value = admin

    await service.update(admin.id, UserUpdate(is_active=False, full_name="New Name"))

    assert (admin.is_active, admin.full_name) == (False, "New Name")
    service.session.commit.assert_awaited_once()


@pytest.mark.parametrize("target", [{"is_super_admin": True}, {"email": SERVICE_ACCOUNT_EMAIL}])
async def test_update_hides_super_admin_and_service_account(
    service: UserService, target: dict
) -> None:
    user = make_user(**target)
    service.repo.get.return_value = user

    with pytest.raises(NotFoundError, match="User not found"):
        await service.update(user.id, UserUpdate(is_active=False))
    assert user.is_active is True


async def test_update_ignores_null_values(service: UserService) -> None:
    admin = make_user(full_name="Keep Me")
    service.repo.get.return_value = admin

    await service.update(admin.id, UserUpdate(full_name=None))

    assert admin.full_name == "Keep Me"


async def test_service_account_is_created_once(service: UserService) -> None:
    account = await service.get_or_create_service_account()

    assert account.email == SERVICE_ACCOUNT_EMAIL
    assert account.role == UserRole.ADMIN
    service.repo.add.assert_awaited_once()


async def test_existing_service_account_is_reused(service: UserService) -> None:
    existing = make_user(email=SERVICE_ACCOUNT_EMAIL)
    service.repo.get_by_email.return_value = existing

    assert await service.get_or_create_service_account() is existing
    service.repo.add.assert_not_awaited()
