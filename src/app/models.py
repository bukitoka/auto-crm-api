"""Imports every ORM model so `Base.metadata` knows all tables (used by Alembic)."""

from app.modules.activities.models import Activity
from app.modules.assistant.models import Conversation, ConversationMessage
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.pipeline.models import PipelineStage
from app.modules.tasks.models import Task
from app.modules.users.models import User
from app.modules.webhooks.models import WebhookSubscription
from app.shared.models import Base

__all__ = [
    "Activity",
    "Base",
    "Company",
    "Contact",
    "Conversation",
    "ConversationMessage",
    "Deal",
    "PipelineStage",
    "Task",
    "User",
    "WebhookSubscription",
]
