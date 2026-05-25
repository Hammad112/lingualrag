"""Document upload + background processing pipeline."""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
import uuid

import aiofiles
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.documents.models import Document
from app.documents.extractors import extract_text
from app.documents.chunker import chunk_pages, aggregate_languages
from app.embeddings.embedder import embed_texts
from app.vector_store.store import upsert_chunks

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXT = {".pdf", ".docx", ".txt", ".md"}


class DocumentService:
    async def upload_and_process(self, file: UploadFile, user_id: str, db: AsyncSession) -> dict:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(415, f"Unsupported file type: {ext}")

        content = await file.read()
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, "File exceeds 25MB limit")
        if not content:
            raise HTTPException(400, "Empty file")

        stored_name = f"{uuid.uuid4()}{ext}"
        storage_path = ""
        if settings.PERSIST_UPLOADS:
            os.makedirs(settings.STORAGE_DIR, exist_ok=True)
            storage_path = os.path.join(settings.STORAGE_DIR, stored_name)
            async with aiofiles.open(storage_path, "wb") as f:
                await f.write(content)

        doc = Document(
            user_id=user_id,
            filename=stored_name,
            original_filename=file.filename,
            file_size=len(content),
            file_type=ext.lstrip("."),
            storage_path=storage_path,
            status="processing",
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        # Kick off background processing
        asyncio.create_task(self._process(doc.id, content, file.filename))

        return {
            "id": doc.id,
            "name": doc.original_filename,
            "size": doc.file_size,
            "uploadedAt": doc.created_at.isoformat(),
            "status": "processing",
        }

    async def _process(self, doc_id: str, content: bytes, filename: str):
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Document).where(Document.id == doc_id))
            doc = r.scalar_one_or_none()
            if not doc:
                return
            try:
                pages = extract_text(filename, content)
                if not pages:
                    raise ValueError("No text could be extracted from this file")

                chunks = chunk_pages(
                    pages,
                    chunk_size=settings.CHUNK_SIZE,
                    overlap=settings.CHUNK_OVERLAP,
                    filename=filename,
                )
                if not chunks:
                    raise ValueError("Document produced zero chunks")

                texts = [c["text"] for c in chunks]
                vectors = await embed_texts(texts)

                await upsert_chunks(
                    doc_id=doc.id,
                    user_id=doc.user_id,
                    chunks=chunks,
                    vectors=vectors,
                )

                langs = aggregate_languages(chunks)
                doc.languages = langs
                doc.detected_language = next(iter(langs)) if langs else "en"
                doc.chunk_count = len(chunks)
                doc.status = "ready"
                doc.updated_at = datetime.utcnow()
                await db.commit()
                logger.info("Processed %s: %d chunks, lang=%s", doc.original_filename, len(chunks), doc.detected_language)
            except Exception as e:
                logger.exception("Document processing failed for %s", doc.original_filename)
                doc.status = "error"
                doc.error_message = str(e)
                await db.commit()


document_service = DocumentService()
