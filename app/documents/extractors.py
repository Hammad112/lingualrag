"""Extract text from PDF / DOCX / TXT, returning page-level text."""
import io
from typing import List, Tuple


def extract_pdf(content: bytes) -> List[Tuple[int, str]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append((i, text))
    return pages


def extract_docx(content: bytes) -> List[Tuple[int, str]]:
    from docx import Document as DocxDocument
    doc = DocxDocument(io.BytesIO(content))
    full = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(1, full)] if full else []


def extract_txt(content: bytes) -> List[Tuple[int, str]]:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = content.decode(enc)
            return [(1, text)] if text.strip() else []
        except UnicodeDecodeError:
            continue
    return []


def extract_text(filename: str, content: bytes) -> List[Tuple[int, str]]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_pdf(content)
    if lower.endswith(".docx"):
        return extract_docx(content)
    if lower.endswith(".doc"):
        # python-docx doesn't read legacy .doc — return error path
        raise ValueError("Legacy .doc not supported — please convert to .docx or PDF")
    if lower.endswith(".txt") or lower.endswith(".md"):
        return extract_txt(content)
    raise ValueError(f"Unsupported file type: {filename}")
