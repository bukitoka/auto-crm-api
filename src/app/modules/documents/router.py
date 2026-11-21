import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status
from pydantic import Field

from app.core.database import SessionDep
from app.core.exceptions import BadRequestError
from app.core.storage import StorageDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.documents.service import DocumentInput, DocumentRead, DocumentService
from app.shared.record_links import RecordLinks

router = APIRouter(prefix="/documents", tags=["documents"])


def document_service(
    session: SessionDep, user: CurrentUser, storage: StorageDep
) -> DocumentService:
    return DocumentService(session, user, storage)


Service = Annotated[DocumentService, Depends(document_service)]


class DocumentFilters(RecordLinks):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0)


@router.get("", response_model=list[DocumentRead])
async def list_documents(service: Service, filters: Annotated[DocumentFilters, Query()]):
    return await service.list_documents(filters, filters.search, filters.offset)


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    service: Service,
    file: UploadFile,
    notes: Annotated[str | None, Form(max_length=1000)] = None,
    contact_id: Annotated[uuid.UUID | None, Form()] = None,
    company_id: Annotated[uuid.UUID | None, Form()] = None,
    deal_id: Annotated[uuid.UUID | None, Form()] = None,
):
    if sum(value is not None for value in (contact_id, company_id, deal_id)) > 1:
        raise BadRequestError("Select one linked CRM record")
    return await service.upload(
        DocumentInput(notes=notes, contact_id=contact_id, company_id=company_id, deal_id=deal_id),
        file,
    )


@router.put("/{document_id}", response_model=DocumentRead)
async def update_document(document_id: uuid.UUID, data: DocumentInput, service: Service):
    return await service.update(document_id, data)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID, service: Service, preview: bool = False
) -> dict[str, str]:
    item = await service.get(document_id)
    if preview and not item.content_type.startswith("image/"):
        raise BadRequestError("Only pictures can be previewed")
    return {
        "url": service.storage.download_url(
            item.object_key,
            item.filename,
            inline_type=item.content_type if preview else None,
        )
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, service: Service):
    await service.delete(document_id)
