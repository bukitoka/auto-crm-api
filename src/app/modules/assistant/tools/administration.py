"""Account and automation tools, including super-admin-only operations."""

import secrets
import uuid
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.modules.assistant.tools.definitions import NoParams, ToolContext
from app.modules.assistant.tools.results import _page
from app.modules.users.schemas import AdminCreate, UserUpdate


async def list_users(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    page = await ctx.users.list_page(_page(100), None, viewer=ctx.user)
    return {
        "users": [
            {
                "id": str(u.id),
                "name": u.full_name,
                "email": u.email,
                "active": u.is_active,
            }
            for u in page.items
        ],
        "current_user_id": str(ctx.user.id),
    }


class CreateAdminParams(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)


async def create_admin(ctx: ToolContext, params: CreateAdminParams) -> dict[str, Any]:
    password = secrets.token_urlsafe(12)
    admin = await ctx.users.create_admin(
        AdminCreate(email=params.email, password=password, full_name=params.full_name)
    )
    return {
        "created_admin": {"id": str(admin.id), "name": admin.full_name, "email": admin.email},
        "temporary_password": password,
    }


class SetAdminActiveParams(BaseModel):
    user_id: uuid.UUID = Field(description="An admin from list_users")
    active: bool


async def set_admin_active(ctx: ToolContext, params: SetAdminActiveParams) -> dict[str, Any]:
    admin = await ctx.users.update(params.user_id, UserUpdate(is_active=params.active))
    return {"admin": {"id": str(admin.id), "name": admin.full_name, "active": admin.is_active}}


async def list_automations(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    page = await ctx.webhooks.list_page(_page(50))
    return {
        "webhook_subscriptions": [
            {"event": w.event, "target_url": w.target_url, "active": w.is_active}
            for w in page.items
        ]
    }
