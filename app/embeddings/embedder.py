"""Multilingual embeddings via Google AI Studio (Gemini).

No local model — keeps the deployed footprint under Render's 512 MB limit.
Requires GEMINI_API_KEY set in the environment.
"""
import logging
from typing import List

from app.config import settings
from app.embeddings.gemini_api import embed_texts_gemini

logger = logging.getLogger(__name__)


def warm_up():
    logger.info(
        "Embeddings → Gemini (model=%s, dim=%d)",
        settings.EMBEDDING_MODEL,
        settings.EMBEDDING_DIM,
    )
    if not settings.GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY is empty — embedding requests will fail. "
            "Get a free key at https://aistudio.google.com/apikey"
        )


async def embed_texts(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
    if not texts:
        return []
    return await embed_texts_gemini(texts, task_type=task_type)
