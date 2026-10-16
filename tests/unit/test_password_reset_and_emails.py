from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestError, EmailDeliveryError
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_access_token,
    decode_password_reset_token,
    password_matches_fingerprint,
    verify_password,
)
from app.modules.activities.models import ActivityType
from app.modules.auth.schemas import ForgotPasswordRequest, ResetPasswordRequest
from app.modules.auth.service import AuthService
from app.modules.companies.service import CompanyService
from app.modules.contacts.service import ContactService
from app.modules.emails.schemas import EmailSendRequest
from app.modules.emails.service import EmailService
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL, UserService
from tests.fakes import FakeMailer, FakeStorage
from tests.unit.conftest import make_activity, make_company, make_contact, make_user, mock_repos


def test_reset_token_round_trip() -> None:
    user = make_user()
    token = create_password_reset_token(user.id, "hash-1")

    decoded = decode_password_reset_token(token)

    assert decoded is not None
    user_id, fingerprint = decoded
    assert user_id == user.id
    assert password_matches_fingerprint("hash-1", fingerprint)
    assert not password_matches_fingerprint("hash-2", fingerprint)  # password changed


def test_reset_token_and_access_token_are_not_interchangeable() -> None:
    user = make_user()
    assert decode_access_token(create_password_reset_token(user.id, "hash")) is None
    assert decode_password_reset_token(create_access_token(user.id)) is None
    assert decode_password_reset_token("garbage") is None


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture
def auth(session: AsyncMock, mailer: FakeMailer) -> AuthService:
    service = AuthService(session, mailer)
    mock_repos(service, "user_repo")
    return service


async def test_forgot_password_emails_a_reset_link(auth: AuthService, mailer: FakeMailer) -> None:
    user = make_user(email="uma@example.com")
    auth.user_repo.get_by_email.return_value = user

    await auth.request_password_reset(ForgotPasswordRequest(email="uma@example.com"))

    [mail] = mailer.outbox
    assert mail.to == "uma@example.com"
    assert "/reset-password?token=" in mail.text
    assert mail.html is not None and "Choose a new password" in mail.html


@pytest.mark.parametrize(
    "user",
    [None, make_user(is_active=False), make_user(email=SERVICE_ACCOUNT_EMAIL)],
    ids=["unknown", "inactive", "service-account"],
)
async def test_forgot_password_sends_nothing_for_unusable_accounts(
    auth: AuthService, mailer: FakeMailer, user: object
) -> None:
    auth.user_repo.get_by_email.return_value = user

    await auth.request_password_reset(ForgotPasswordRequest(email="x@example.com"))

    assert mailer.outbox == []


async def test_forgot_password_hides_delivery_failures(auth: AuthService) -> None:
    auth.user_repo.get_by_email.return_value = make_user()
    auth.mailer.send = AsyncMock(side_effect=EmailDeliveryError())

    await auth.request_password_reset(ForgotPasswordRequest(email="u@example.com"))  # no raise


async def test_reset_password_sets_new_hash(auth: AuthService, session: AsyncMock) -> None:
    user = make_user(hashed_password="old-hash")
    auth.user_repo.get.return_value = user
    token = create_password_reset_token(user.id, "old-hash")

    await auth.reset_password(ResetPasswordRequest(token=token, password="brand-new-pass"))

    assert verify_password("brand-new-pass", user.hashed_password)
    session.commit.assert_awaited_once()


async def test_reset_link_works_only_once(auth: AuthService) -> None:
    user = make_user(hashed_password="old-hash")
    auth.user_repo.get.return_value = user
    token = create_password_reset_token(user.id, "old-hash")
    await auth.reset_password(ResetPasswordRequest(token=token, password="first-new-pass"))

    with pytest.raises(BadRequestError, match="invalid or has expired"):
        await auth.reset_password(ResetPasswordRequest(token=token, password="second-new-pass"))


@pytest.mark.parametrize("case", ["bad-token", "unknown-user", "inactive-user"])
async def test_reset_password_rejects_invalid_requests(auth: AuthService, case: str) -> None:
    user = make_user(hashed_password="hash", is_active=case != "inactive-user")
    auth.user_repo.get.return_value = None if case == "unknown-user" else user
    token = "nope" if case == "bad-token" else create_password_reset_token(user.id, "hash")

    with pytest.raises(BadRequestError):
        await auth.reset_password(ResetPasswordRequest(token=token, password="whatever-123"))


@pytest.fixture
def emails(session: AsyncMock, mailer: FakeMailer) -> EmailService:
    service = EmailService(session, mailer)
    service.contacts = AsyncMock()
    service.activities = AsyncMock()
    return service


async def test_send_to_contact_emails_and_logs_activity(
    emails: EmailService, mailer: FakeMailer
) -> None:
    sender = make_user(full_name="Ada Admin", email="ada@example.com")
    contact = make_contact(first_name="Jane", last_name="Doe", email="jane@acme.com")
    emails.contacts.get.return_value = contact
    emails.activities.create.return_value = make_activity(type=ActivityType.EMAIL)

    await emails.send_to_contact(
        EmailSendRequest(contact_id=contact.id, subject="Hello", body="Hi Jane"), user=sender
    )

    [mail] = mailer.outbox
    assert mail.to == "Jane Doe <jane@acme.com>"
    assert mail.from_name == "Ada Admin via Auto CRM"
    assert mail.reply_to == "Ada Admin <ada@example.com>"
    logged = emails.activities.create.await_args.args[0]
    assert (logged.type, logged.subject, logged.contact_id) == (
        ActivityType.EMAIL,
        "Hello",
        contact.id,
    )


async def test_send_to_contact_without_email_is_rejected(
    emails: EmailService, mailer: FakeMailer
) -> None:
    emails.contacts.get.return_value = make_contact(email=None)

    with pytest.raises(BadRequestError, match="no email address"):
        await emails.send_to_contact(
            EmailSendRequest(contact_id=make_contact().id, subject="Hi", body="Hi"),
            user=make_user(),
        )
    assert mailer.outbox == []


async def test_failed_send_is_not_logged(emails: EmailService) -> None:
    emails.contacts.get.return_value = make_contact()
    emails.mailer.send = AsyncMock(side_effect=EmailDeliveryError())

    with pytest.raises(EmailDeliveryError):
        await emails.send_to_contact(
            EmailSendRequest(contact_id=make_contact().id, subject="Hi", body="Hi"),
            user=make_user(),
        )
    emails.activities.create.assert_not_awaited()


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


async def test_contact_avatar_set_replace_and_remove(
    session: AsyncMock, storage: FakeStorage
) -> None:
    service = ContactService(session, storage)
    mock_repos(service, "repo")
    contact = make_contact()
    service.repo.get.return_value = contact

    await service.set_avatar(contact.id, b"first")
    first_key = contact.avatar_key
    await service.set_avatar(contact.id, b"second")

    assert first_key is not None and first_key.startswith(f"contacts/{contact.id}/")
    assert list(storage.files) == [contact.avatar_key]  # the old file was deleted

    await service.remove_avatar(contact.id)
    assert contact.avatar_key is None
    assert storage.files == {}


async def test_deleting_contact_deletes_its_avatar(
    session: AsyncMock, storage: FakeStorage
) -> None:
    service = ContactService(session, storage)
    mock_repos(service, "repo")
    storage.files["contacts/1/a.webp"] = (b"a", "image/webp")
    service.repo.get.return_value = make_contact(avatar_key="contacts/1/a.webp")

    await service.delete(make_contact().id)

    assert storage.files == {}


async def test_remove_avatar_without_one_is_a_no_op(
    session: AsyncMock, storage: FakeStorage
) -> None:
    service = ContactService(session, storage)
    mock_repos(service, "repo")
    service.repo.get.return_value = make_contact()

    await service.remove_avatar(make_contact().id)

    session.commit.assert_not_awaited()


async def test_company_logo_set_remove_and_delete(session: AsyncMock, storage: FakeStorage) -> None:
    service = CompanyService(session, storage)
    mock_repos(service, "repo")
    company = make_company()
    service.repo.get.return_value = company

    await service.set_logo(company.id, b"logo")
    assert company.logo_key is not None and company.logo_key in storage.files

    await service.remove_logo(company.id)
    assert company.logo_key is None and storage.files == {}
    await service.remove_logo(company.id)  # nothing left to remove

    await service.set_logo(company.id, b"logo")
    await service.delete(company.id)
    assert storage.files == {}


async def test_user_avatar_set_and_remove(session: AsyncMock, storage: FakeStorage) -> None:
    service = UserService(session, storage)
    user = make_user()

    await service.set_avatar(user, b"me")
    assert user.avatar_key is not None and user.avatar_key.startswith(f"users/{user.id}/")

    await service.remove_avatar(user)
    assert user.avatar_key is None and storage.files == {}
    await service.remove_avatar(user)  # no-op
