from fastapi import APIRouter, Depends, status

from app.core.rate_limit import login_limiter, password_reset_limiter, setup_limiter
from app.modules.auth.dependencies import AuthServiceDep, CurrentUser
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SetupStatus,
    TokenResponse,
)
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/setup", response_model=SetupStatus)
async def setup_status(service: AuthServiceDep):
    return await service.setup_status()


@router.post(
    "/setup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(setup_limiter)],
)
async def setup(data: RegisterRequest, service: AuthServiceDep):
    """Create the super admin of a new workspace. Answers 409 once the workspace is set up."""
    return await service.setup(data)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_limiter)])
async def login(data: LoginRequest, service: AuthServiceDep):
    return await service.login(data)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser):
    return user


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(password_reset_limiter)],
)
async def forgot_password(data: ForgotPasswordRequest, service: AuthServiceDep):
    """Email a password reset link. Always answers the same way (no account enumeration)."""
    await service.request_password_reset(data)
    return MessageResponse(detail="If that email has an account, a reset link is on its way.")


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(login_limiter)],
)
async def reset_password(data: ResetPasswordRequest, service: AuthServiceDep):
    await service.reset_password(data)
