"""Multilingual embeddings via HuggingFace Inference API (free tier).

No local model — keeps the deployed footprint under Render's 512 MB limit.
Requires HF_API_TOKEN set in the environment.
"""
import logging
from typing import List

from app.config import settings
from app.embeddings.hf_api import embed_texts_hf

logger = logging.getLogger(__name__)


def warm_up():
    logger.info(
        "Embeddings → HuggingFace Inference API (model=%s)",
        settings.EMBEDDING_MODEL,
    )
    if not settings.HF_API_TOKEN:
        logger.warning(
            "HF_API_TOKEN is empty — embedding requests will fail. "
            "Get a free token at https://huggingface.co/settings/tokens"
        )


async def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    return await embed_texts_hf(texts)
