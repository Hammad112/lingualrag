"""Gemini (Google AI Studio) embeddings.

Free tier: very generous (effectively unlimited for indie/small-scale use).
Model: text-embedding-004 → 768-dimensional vectors, multilingual.
Docs: https://ai.google.dev/gemini-api/docs/embeddings
"""
import logging
from typing import List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def embed_texts_gemini(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is empty. Get one at https://aistudio.google.com/apikey"
        )

    model = settings.EMBEDDING_MODEL
    url = f"{_BASE}/models/{model}:batchEmbedContents?key={settings.GEMINI_API_KEY}"

    payload = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
            }
            for t in texts
        ]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini embed error {r.status_code}: {r.text[:500]}")
        data = r.json()

    embeddings = data.get("embeddings") or []
    return [e["values"] for e in embeddings]
