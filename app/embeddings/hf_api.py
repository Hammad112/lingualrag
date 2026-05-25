"""HuggingFace Inference API embeddings — zero local RAM, free tier friendly.

Uses the feature-extraction pipeline. The first request after cold-start may
take 20-30s while the model warms on HF's side; subsequent calls are sub-second.
"""
import asyncio
import logging
from typing import List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_HF_BASE = "https://router.huggingface.co/hf-inference/pipeline/feature-extraction"


async def embed_texts_hf(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    if not settings.HF_API_TOKEN:
        raise RuntimeError("HF_API_TOKEN is empty but EMBEDDING_PROVIDER=hf_api")

    url = f"{_HF_BASE}/{settings.EMBEDDING_MODEL}"
    headers = {"Authorization": f"Bearer {settings.HF_API_TOKEN}"}
    payload = {"inputs": texts, "options": {"wait_for_model": True}}

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            try:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 503:
                    # Model is loading on HF — wait and retry
                    await asyncio.sleep(5 + attempt * 5)
                    continue
                r.raise_for_status()
                data = r.json()
                # HF returns either a single vector (for one input) or a list of vectors.
                # For sentence-similarity models we get list[list[float]].
                if isinstance(data, list) and data and isinstance(data[0], (int, float)):
                    return [data]
                # Some models return token-level [seq_len, dim]; mean-pool to sentence vector.
                if isinstance(data, list) and data and isinstance(data[0], list) and data[0] and isinstance(data[0][0], list):
                    out = []
                    for token_matrix in data:
                        cols = list(zip(*token_matrix))
                        out.append([sum(c) / len(c) for c in cols])
                    return out
                return data
            except httpx.HTTPStatusError as e:
                if attempt == 2:
                    raise RuntimeError(f"HF API error {e.response.status_code}: {e.response.text}") from e
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError("HF API failed after 3 attempts")
