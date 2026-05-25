"""Qdrant wrapper. Uses local file storage if QDRANT_URL is empty, otherwise cloud."""
import asyncio
import logging
from typing import List, Optional
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, MatchAny,
)

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        if settings.QDRANT_URL:
            _client = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
            )
            logger.info("Connected to Qdrant Cloud at %s", settings.QDRANT_URL)
        else:
            _client = QdrantClient(path=settings.QDRANT_PATH)
            logger.info("Using local Qdrant at %s", settings.QDRANT_PATH)
    return _client


def init_collection():
    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION not in collections:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", settings.QDRANT_COLLECTION)


async def upsert_chunks(
    doc_id: str, user_id: str, chunks: List[dict], vectors: List[List[float]]
) -> int:
    client = get_client()
    points = []
    for chunk, vec in zip(chunks, vectors):
        points.append(
            PointStruct(
                id=str(uuid4()),
                vector=vec,
                payload={
                    "doc_id": doc_id,
                    "user_id": user_id,
                    "page": chunk.get("page", 1),
                    "text": chunk["text"],
                    "lang": chunk.get("lang", "en"),
                    "filename": chunk.get("filename", ""),
                    "chunk_index": chunk.get("chunk_index", 0),
                },
            )
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points),
    )
    return len(points)


async def dense_search(
    query_vector: List[float],
    user_id: str,
    doc_ids: Optional[List[str]] = None,
    top_k: int = 20,
):
    client = get_client()

    must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    if doc_ids:
        must.append(FieldCondition(key="doc_id", match=MatchAny(any=doc_ids)))

    qfilter = Filter(must=must)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_vector,
            query_filter=qfilter,
            limit=top_k,
        ),
    )
    return results


async def delete_document_vectors(doc_id: str):
    client = get_client()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        ),
    )
