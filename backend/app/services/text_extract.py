"""Extract plain text from an uploaded reference (docx / txt / md / pdf)."""

from __future__ import annotations

import io

from app.core.errors import ApiError

MAX_CHARS = 300_000


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        text = _docx(data)
    elif name.endswith(".pdf"):
        text = _pdf(data)
    elif name.endswith((".txt", ".md", ".markdown")):
        text = data.decode("utf-8", errors="replace")
    else:
        # Best-effort UTF-8 for unknown text-like uploads.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ApiError(
                400,
                "Unsupported file type. Attach a .docx, .txt, .md, or .pdf.",
                "UNSUPPORTED_FILE",
            ) from e
    text = text.replace("\x00", "").strip()
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS]
    return text


def _docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise ApiError(500, "Document extraction is not available.") from e
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ApiError(500, "PDF extraction is not available.") from e
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def word_count(text: str) -> int:
    return len([w for w in text.split() if w])
