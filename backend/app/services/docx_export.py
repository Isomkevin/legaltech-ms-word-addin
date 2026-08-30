"""Build a simple .docx from stored draft text for insertFileFromBase64."""

from __future__ import annotations

import io
from typing import Any

from docx import Document
from docx.shared import Pt


def draft_to_docx_bytes(title: str, content: dict[str, Any] | None, fallback_text: str = "") -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    if content and isinstance(content.get("content"), list):
        _walk(doc, content["content"], title_written=False)
    elif fallback_text:
        doc.add_heading(title, level=1)
        for para in fallback_text.split("\n\n"):
            if para.strip():
                doc.add_paragraph(para.strip())
    else:
        doc.add_heading(title or "Draft", level=1)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _node_text(node: dict[str, Any]) -> str:
    if isinstance(node.get("text"), str):
        return node["text"]
    children = node.get("content")
    if isinstance(children, list):
        return "".join(_node_text(c) for c in children if isinstance(c, dict))
    return ""


def _walk(doc: Document, blocks: list[Any], title_written: bool) -> None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        text = _node_text(block).strip()
        if kind == "heading":
            level = 1
            attrs = block.get("attrs") or {}
            if isinstance(attrs.get("level"), int):
                level = max(1, min(3, attrs["level"]))
            if text:
                doc.add_heading(text, level=level)
        elif text:
            doc.add_paragraph(text)
