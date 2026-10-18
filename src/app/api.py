from fastapi import APIRouter

from app.modules.activities.router import router as activities_router
from app.modules.ai.router import router as ai_router
from app.modules.assistant.router import router as assistant_router
from app.modules.auth.router import router as auth_router
from app.modules.companies.router import router as companies_router
from app.modules.contacts.router import router as contacts_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.deals.router import router as deals_router
from app.modules.emails.router import router as emails_router
from app.modules.integrations.router import router as integrations_router
from app.modules.pipeline.router import router as pipeline_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router
from app.modules.webhooks.router import router as webhooks_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(companies_router)
api_router.include_router(contacts_router)
api_router.include_router(pipeline_router)
api_router.include_router(deals_router)
api_router.include_router(activities_router)
api_router.include_router(tasks_router)
api_router.include_router(dashboard_router)
api_router.include_router(ai_router)
api_router.include_router(assistant_router)
api_router.include_router(emails_router)
api_router.include_router(webhooks_router)
api_router.include_router(integrations_router)
