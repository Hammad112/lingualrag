"""Qdrant wrapper. Uses local file storage if QDRANT_URL is empty, otherwise cloud."""
import asyncio
import logging
from typing import List, Optional
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, MatchAny,
    PayloadSchemaType,
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
    name = settings.QDRANT_COLLECTION
    dim = settings.EMBEDDING_DIM
    collections = [c.name for c in client.get_collections().collections]

    if name in collections:
        info = client.get_collection(name)
        existing_dim = info.config.params.vectors.size
        if existing_dim != dim:
            logger.warning(
                "Qdrant collection %s has dim=%d but EMBEDDING_DIM=%d. Recreating (existing vectors will be lost).",
                name, existing_dim, dim,
            )
            client.delete_collection(name)
            collections.remove(name)

    if name not in collections:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s (dim=%d)", name, dim)

    # Payload indexes required for filtered search on these fields.
    # Skip fields that already have an index — Qdrant 400s on duplicate creates.
    existing_indexes = set((client.get_collection(name).payload_schema or {}).keys())
    for field in ("user_id", "doc_id"):
        if field in existing_indexes:
            continue
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created Qdrant payload index for %s", field)
        except Exception as e:
            logger.warning("Failed to create payload index for %s: %s", field, e)


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
