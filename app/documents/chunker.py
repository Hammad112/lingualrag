"""Simple text chunker that splits on paragraph + sentence boundaries while respecting CJK / RTL."""
import re
from typing import List, Tuple
from collections import Counter

from langdetect import detect, DetectorFactory
DetectorFactory.seed = 0


_SENT_SPLIT = re.compile(
    r"(?<=[.!?؟。！？])\s+|(?<=[\n])\s*",
    re.UNICODE,
)


def detect_language_safe(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "en"
    try:
        return detect(text[:2000])
    except Exception:
        return "en"


def _split_sentences(text: str) -> List[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return parts


def chunk_pages(
    pages: List[Tuple[int, str]],
    chunk_size: int = 500,
    overlap: int = 80,
    filename: str = "",
) -> List[dict]:
    """Return list of dicts: {text, page, lang, chunk_index, filename}."""
    chunks: List[dict] = []
    idx = 0

    for page_num, page_text in pages:
        sentences = _split_sentences(page_text)
        buf: List[str] = []
        buf_len = 0
        for s in sentences:
            s_len = len(s)
            if buf_len + s_len > chunk_size and buf:
                text = " ".join(buf).strip()
                lang = detect_language_safe(text)
                chunks.append({
                    "text": text,
                    "page": page_num,
                    "lang": lang,
                    "chunk_index": idx,
                    "filename": filename,
                })
                idx += 1
                # overlap
                if overlap > 0 and buf:
                    keep = []
                    keep_len = 0
                    for x in reversed(buf):
                        if keep_len + len(x) > overlap:
                            break
                        keep.insert(0, x)
                        keep_len += len(x)
                    buf = keep
                    buf_len = keep_len
                else:
                    buf, buf_len = [], 0
            buf.append(s)
            buf_len += s_len + 1

        if buf:
            text = " ".join(buf).strip()
            if text:
                lang = detect_language_safe(text)
                chunks.append({
                    "text": text,
                    "page": page_num,
                    "lang": lang,
                    "chunk_index": idx,
                    "filename": filename,
                })
                idx += 1

    return chunks


def aggregate_languages(chunks: List[dict]) -> dict:
    counter = Counter(c["lang"] for c in chunks)
    total = sum(counter.values()) or 1
    return {lang: round(c / total, 3) for lang, c in counter.most_common()}
