from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import verify_password
from app.modules.users.models import UserRole
from app.modules.users.schemas import UserUpdate
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL, UserService
from app.shared.pagination import PageParams
from tests.unit.conftest import make_user, mock_repos


@pytest.fixture
def service(session: AsyncMock) -> UserService:
    service = UserService(session)
    mock_repos(service, "repo")
    service.repo.get_by_email.return_value = None
    service.repo.super_admin_exists.return_value = True
    return service


async def test_sign_ups_become_members(service: UserService) -> None:
    user = await service.create(email="next@example.com", password="pw123456", full_name="Next")

    assert (user.role, user.is_super_admin) == (UserRole.MEMBER, False)
    service.session.commit.assert_awaited_once()


async def test_sign_ups_need_a_set_up_workspace(service: UserService) -> None:
    service.repo.super_admin_exists.return_value = False

    with pytest.raises(PermissionDeniedError, match="Finish setting up"):
        await service.create(email="a@example.com", password="pw123456", full_name="A")
    service.session.commit.assert_not_awaited()


async def test_setup_creates_the_super_admin_once(service: UserService) -> None:
    service.repo.super_admin_exists.return_value = False
    user = await service.setup(email="Root@Example.com", password="pw123456", full_name="Root")
    assert (user.email, user.is_super_admin, user.is_admin) == ("root@example.com", True, True)

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


async def test_create_lowercases_email_and_hashes_password(service: UserService) -> None:
    user = await service.create(email="Mixed@Example.COM", password="pw123456", full_name="M")

    assert user.email == "mixed@example.com"
    assert verify_password("pw123456", user.hashed_password)


async def test_create_with_existing_email_conflicts(service: UserService) -> None:
    service.repo.get_by_email.return_value = make_user()

    with pytest.raises(ConflictError, match="already exists"):
        await service.create(email="user@example.com", password="pw123456", full_name="Dup")
    service.session.commit.assert_not_awaited()


async def test_get_unknown_user_is_not_found(service: UserService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="User not found"):
        await service.get(make_user().id)


async def test_list_page_wraps_repository_results(service: UserService) -> None:
    service.repo.list_page.return_value = ([make_user()], 1)

    page = await service.list_page(PageParams(page=1, size=20), search="uma")

    assert page.total == 1
    service.repo.list_page.assert_awaited_once_with(search="uma", offset=0, limit=20)


@pytest.mark.parametrize(
    "changes", [{"role": UserRole.MEMBER}, {"is_active": False}], ids=["demote", "deactivate"]
)
async def test_admin_cannot_demote_or_deactivate_self(service: UserService, changes: dict) -> None:
    admin = make_user(role=UserRole.ADMIN)
    service.repo.get.return_value = admin

    with pytest.raises(BadRequestError, match="cannot change your own role or deactivate"):
        await service.update(admin.id, UserUpdate(**changes), acting_user=admin)
    assert admin.role == UserRole.ADMIN
    assert admin.is_active is True


async def test_admin_can_rename_self(service: UserService) -> None:
    admin = make_user(role=UserRole.ADMIN)
    service.repo.get.return_value = admin

    updated = await service.update(admin.id, UserUpdate(full_name="New Name"), acting_user=admin)

    assert updated.full_name == "New Name"


async def test_super_admin_can_promote_a_member(service: UserService) -> None:
    admin = make_user(role=UserRole.ADMIN, is_super_admin=True)
    member = make_user(role=UserRole.MEMBER)
    service.repo.get.return_value = member

    updated = await service.update(member.id, UserUpdate(role=UserRole.ADMIN), acting_user=admin)

    assert updated.role == UserRole.ADMIN
    service.session.commit.assert_awaited_once()


async def test_admins_cannot_make_admins(service: UserService) -> None:
    member = make_user(role=UserRole.MEMBER)
    service.repo.get.return_value = member

    with pytest.raises(PermissionDeniedError, match="Only the super admin"):
        await service.update(
            member.id, UserUpdate(role=UserRole.ADMIN), acting_user=make_user(role=UserRole.ADMIN)
        )
    assert member.role == UserRole.MEMBER


@pytest.mark.parametrize(
    "changes",
    [{"role": UserRole.MEMBER}, {"is_active": False}, {"full_name": "X"}],
    ids=["demote", "deactivate", "rename"],
)
async def test_admins_cannot_change_other_admins(service: UserService, changes: dict) -> None:
    other = make_user(role=UserRole.ADMIN)
    service.repo.get.return_value = other

    with pytest.raises(PermissionDeniedError, match="Only the super admin"):
        await service.update(
            other.id, UserUpdate(**changes), acting_user=make_user(role=UserRole.ADMIN)
        )
    service.session.commit.assert_not_awaited()


async def test_admin_can_deactivate_a_member(service: UserService) -> None:
    member = make_user(role=UserRole.MEMBER)
    service.repo.get.return_value = member

    await service.update(
        member.id, UserUpdate(is_active=False), acting_user=make_user(role=UserRole.ADMIN)
    )

    assert member.is_active is False


async def test_super_admin_can_demote_an_admin(service: UserService) -> None:
    other = make_user(role=UserRole.ADMIN)
    service.repo.get.return_value = other

    await service.update(
        other.id,
        UserUpdate(role=UserRole.MEMBER),
        acting_user=make_user(role=UserRole.ADMIN, is_super_admin=True),
    )

    assert other.role == UserRole.MEMBER


async def test_super_admins_cannot_be_changed_through_the_api(service: UserService) -> None:
    root = make_user(role=UserRole.ADMIN, is_super_admin=True)
    service.repo.get.return_value = root

    with pytest.raises(NotFoundError, match="User not found"):
        await service.update(
            root.id,
            UserUpdate(is_active=False),
            acting_user=make_user(role=UserRole.ADMIN, is_super_admin=True),
        )
    assert root.is_active is True


async def test_update_ignores_null_values(service: UserService) -> None:
    admin = make_user(role=UserRole.ADMIN)
    member = make_user(full_name="Keep Me")
    service.repo.get.return_value = member

    await service.update(member.id, UserUpdate(full_name=None), acting_user=admin)

    assert member.full_name == "Keep Me"


async def test_service_account_is_created_once(service: UserService) -> None:
    account = await service.get_or_create_service_account()

    assert account.email == SERVICE_ACCOUNT_EMAIL
    assert account.role == UserRole.MEMBER
    service.repo.add.assert_awaited_once()


async def test_existing_service_account_is_reused(service: UserService) -> None:
    existing = make_user(email=SERVICE_ACCOUNT_EMAIL)
    service.repo.get_by_email.return_value = existing

    assert await service.get_or_create_service_account() is existing
    service.repo.add.assert_not_awaited()
