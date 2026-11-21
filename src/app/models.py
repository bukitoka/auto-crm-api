"""Imports every ORM model so `Base.metadata` knows all tables (used by Alembic)."""

from app.modules.activities.models import Activity
from app.modules.assistant.models import Conversation, ConversationMessage
from app.modules.calendar.models import CalendarEvent
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.documents.models import Document
from app.modules.integrations.models import LeadRouting
from app.modules.pipeline.models import PipelineStage
from app.modules.tasks.models import Task
from app.modules.users.models import User
from app.modules.webhooks.models import WebhookDelivery, WebhookSubscription
from app.modules.workspace_sync.models import SyncImport
from app.shared.models import Base

__all__ = [
    "Activity",
    "Base",
    "CalendarEvent",
    "Company",
    "Contact",
    "Conversation",
    "ConversationMessage",
    "Deal",
    "Document",
    "LeadRouting",
    "PipelineStage",
    "SyncImport",
    "Task",
    "User",
    "WebhookDelivery",
    "WebhookSubscription",
]
