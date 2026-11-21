from __future__ import annotations

import asyncio
import io
import re
import uuid
from pathlib import PurePosixPath

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError, PayloadTooLargeError
from app.core.storage import Storage
from app.modules.ai.documents import extract_text
from app.modules.documents.models import Document
from app.modules.users.models import User
from app.shared.images import ALLOWED_FORMATS
from app.shared.record_links import RECORD_MODELS, RecordLinks, validate_link
from app.shared.schemas import ORMModel

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".eml": "message/rfc822",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".vcf": "text/vcard",
}


def _image_mime(content: bytes) -> str:
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise BadRequestError("Upload a JPEG, PNG, WebP or GIF image")
            mime = Image.MIME[image.format]
            image.verify()
            return mime
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise BadRequestError("The file is not a valid image") from exc


class DocumentInput(RecordLinks):
    notes: str | None = Field(default=None, max_length=1000)


class DocumentRead(ORMModel, DocumentInput):
    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    created_at: str

    @classmethod
    def from_document(cls, document: Document) -> DocumentRead:
        return cls(
            id=document.id,
            filename=document.filename,
            notes=document.notes,
            content_type=document.content_type,
            size=document.size,
            contact_id=document.contact_id,
            company_id=document.company_id,
            deal_id=document.deal_id,
            created_at=document.created_at.isoformat(),
        )


class DocumentService:
    def __init__(self, session: AsyncSession, user: User, storage: Storage) -> None:
        self.session = session
        self.user = user
        self.storage = storage

    async def list_documents(
        self, links: RecordLinks, search: str = "", offset: int = 0
    ) -> list[DocumentRead]:
        query = select(Document).where(Document.owner_id == self.user.id)
        for key in RECORD_MODELS:
            if (record_id := getattr(links, key)) is not None:
                query = query.where(getattr(Document, key) == record_id)
        if search:
            query = query.where(
                or_(
                    Document.filename.icontains(search, autoescape=True),
                    Document.notes.icontains(search, autoescape=True),
                )
            )
        items = await self.session.scalars(
            query.order_by(Document.created_at.desc(), Document.id.desc()).offset(offset).limit(25)
        )
        return [DocumentRead.from_document(item) for item in items]

    async def get(self, document_id: uuid.UUID) -> Document:
        item = await self.session.scalar(
            select(Document).where(Document.id == document_id, Document.owner_id == self.user.id)
        )
        if item is None:
            raise NotFoundError("Document not found")
        return item

    async def upload(self, data: DocumentInput, file: UploadFile) -> DocumentRead:
        await validate_link(self.session, data)
        filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
        filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()
        extension = PurePosixPath(filename).suffix.lower()
        if not filename or len(filename) > 200:
            raise BadRequestError("Use a filename of up to 200 characters")
        if extension not in IMAGE_TYPES and extension not in DOCUMENT_TYPES:
            raise BadRequestError("Upload a JPEG, PNG, WebP, GIF, PDF, DOCX, EML or text file")
        content = await file.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise PayloadTooLargeError("Documents can be at most 4 MB")
        if not content:
            raise BadRequestError("Choose a file to upload")
        if extension in IMAGE_TYPES:
            mime = await asyncio.to_thread(_image_mime, content)
        else:
            mime = DOCUMENT_TYPES[extension]
        object_key = f"documents/{self.user.id}/{uuid.uuid4().hex}"
        await self.storage.put(object_key, content, "application/octet-stream")
        item = Document(
            owner_id=self.user.id,
            filename=filename,
            size=len(content),
            content_type=mime,
            object_key=object_key,
            **data.model_dump(),
        )
        self.session.add(item)
        try:
            await self.session.commit()
        except Exception:
            await self.storage.delete(object_key)
            raise
        return DocumentRead.from_document(item)

    async def update(self, document_id: uuid.UUID, data: DocumentInput) -> DocumentRead:
        item = await self.get(document_id)
        await validate_link(self.session, data)
        for key, value in data.model_dump().items():
            setattr(item, key, value)
        await self.session.commit()
        return DocumentRead.from_document(item)

    async def delete(self, document_id: uuid.UUID) -> None:
        item = await self.get(document_id)
        key = item.object_key
        await self.session.delete(item)
        await self.session.commit()
        await self.storage.delete(key)

    async def read_text(self, document_id: uuid.UUID) -> str:
        item = await self.get(document_id)
        content = await self.storage.read(item.object_key, MAX_DOCUMENT_BYTES)
        return await asyncio.to_thread(extract_text, item.filename, item.content_type, content)
