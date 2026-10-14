"""Turn an uploaded file into plain text for the AI (smart capture).

DeepSeek only reads text, so every file is converted first:

| File                         | How                                                |
| ---------------------------- | -------------------------------------------------- |
| Image (JPEG, PNG, WebP, GIF) | OCR with RapidOCR (runs locally, models included)  |
| PDF                          | the PDF's text; scanned pages fall back to OCR     |
| Word (.docx)                 | paragraphs and tables                              |
| Email (.eml)                 | headers (From, Subject…) and the plain-text body   |
| Text (.txt, .csv, .md, .vcf) | read as UTF-8                                      |
"""

import asyncio
import io
import logging
from email import policy
from email.parser import BytesParser
from functools import lru_cache
from pathlib import PurePath

import docx
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from rapidocr import RapidOCR

from app.core.exceptions import BadRequestError, PayloadTooLargeError

logger = logging.getLogger(__name__)
logging.getLogger("RapidOCR").setLevel(logging.WARNING)  # it logs every model load at INFO

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 8000  # enough for a long email; keeps the prompt small
MAX_PDF_PAGES = 5

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".vcf", ".text"}
SUPPORTED = "an image, PDF, Word (.docx), email (.eml) or text file"


@lru_cache
def _ocr_engine() -> RapidOCR:
    """Created on first use (loading the models takes a moment), then reused."""
    return RapidOCR()


def ocr_image(image: Image.Image) -> str:
    result = _ocr_engine()(image.convert("RGB"))
    return "\n".join(getattr(result, "txts", None) or ())


def _from_image(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return ocr_image(image)
    except (UnidentifiedImageError, OSError) as exc:
        raise BadRequestError("The image could not be read") from exc


def _from_pdf(data: bytes) -> str:
    try:
        pages = PdfReader(io.BytesIO(data)).pages[:MAX_PDF_PAGES]
        text = "\n".join(page.extract_text() or "" for page in pages).strip()
        if text:
            return text
        # A scanned PDF has no text layer: read the pictures on its pages instead.
        pictures = [picture.image for page in pages for picture in page.images]
        return "\n".join(ocr_image(image) for image in pictures if isinstance(image, Image.Image))
    except (PdfReadError, OSError, ValueError) as exc:
        raise BadRequestError("The PDF could not be read") from exc


def _from_docx(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several unrelated error types
        raise BadRequestError("The Word document could not be read") from exc
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        lines.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
    return "\n".join(lines)


def _from_email(data: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(data)
    headers = [f"{name}: {message[name]}" for name in ("From", "To", "Subject") if message[name]]
    body = message.get_body(preferencelist=("plain", "html"))
    content = body.get_content() if body is not None else ""
    return "\n".join([*headers, "", content])


def extract_text(filename: str, content_type: str, data: bytes) -> str:
    """Plain text from a file, cut to MAX_TEXT_CHARS. Raises BadRequestError when there is none."""
    extension = PurePath(filename).suffix.lower()
    if content_type.startswith("image/") or extension in IMAGE_EXTENSIONS:
        text = _from_image(data)
    elif content_type == "application/pdf" or extension == ".pdf":
        text = _from_pdf(data)
    elif extension == ".docx":
        text = _from_docx(data)
    elif content_type == "message/rfc822" or extension == ".eml":
        text = _from_email(data)
    elif content_type.startswith("text/") or extension in TEXT_EXTENSIONS:
        text = data.decode("utf-8", errors="replace")
    else:
        raise BadRequestError(f"Unsupported file. Upload {SUPPORTED}.")

    text = text.strip()
    if not text:
        raise BadRequestError("No text was found in this file")
    return text[:MAX_TEXT_CHARS]


async def read_upload_text(upload: UploadFile) -> str:
    """Read an uploaded file (max 5 MB) and extract its text in a worker thread."""
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise PayloadTooLargeError("Files can be at most 5 MB")
    if not data:
        raise BadRequestError("The uploaded file is empty")
    return await asyncio.to_thread(
        extract_text, upload.filename or "", upload.content_type or "", data
    )
