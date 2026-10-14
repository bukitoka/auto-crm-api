import uuid

from fastapi import APIRouter, UploadFile

from app.modules.ai.dependencies import AIServiceDep
from app.modules.ai.documents import read_upload_text
from app.modules.ai.schemas import (
    CapturedContact,
    EmailDraft,
    EmailDraftRequest,
    ExtractContactRequest,
    ExtractedContact,
    LeadScore,
    SummarizeRequest,
    TimelineSummary,
)
from app.modules.auth.dependencies import CurrentUser

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/contacts/{contact_id}/score", response_model=LeadScore)
async def score_contact(contact_id: uuid.UUID, _: CurrentUser, service: AIServiceDep):
    return await service.score_contact(contact_id)


@router.post("/email-draft", response_model=EmailDraft)
async def draft_email(data: EmailDraftRequest, _: CurrentUser, service: AIServiceDep):
    return await service.draft_email(data)


@router.post("/summarize", response_model=TimelineSummary)
async def summarize(data: SummarizeRequest, _: CurrentUser, service: AIServiceDep):
    return await service.summarize(data)


@router.post("/extract-contact", response_model=ExtractedContact)
async def extract_contact(data: ExtractContactRequest, _: CurrentUser, service: AIServiceDep):
    return await service.extract_contact(data)


@router.post("/extract-contact/file", response_model=CapturedContact)
async def extract_contact_from_file(file: UploadFile, _: CurrentUser, service: AIServiceDep):
    """Smart capture from a business-card photo, screenshot, PDF, Word, email or text file."""
    return await service.capture_contact(await read_upload_text(file))
