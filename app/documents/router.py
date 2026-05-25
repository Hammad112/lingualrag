from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.documents.service import document_service
from app.documents.models import Document
from app.vector_store.store import delete_document_vectors

router = APIRouter()


def _doc_to_dict(d: Document) -> dict:
    return {
        "id": d.id,
        "name": d.original_filename,
        "size": d.file_size,
        "uploadedAt": d.created_at.isoformat() if d.created_at else None,
        "status": d.status,
        "language": d.detected_language,
        "languages": d.languages or {},
        "pages": d.chunk_count,
        "error": d.error_message,
    }


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.upload_and_process(file, current_user["user_id"], db)


# Frontend uses both `GET /documents` (no trailing slash) and `GET /documents/`.
# Register a non-redirecting handler at the empty string so it accepts both.
@router.get("")
@router.get("/")
async def list_documents(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Document)
        .where(Document.user_id == current_user["user_id"])
        .order_by(desc(Document.created_at))
    )
    docs = [_doc_to_dict(d) for d in r.scalars().all()]
    return {"documents": docs}


@router.get("/{doc_id}/status")
async def status(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user["user_id"])
    )
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document not found")
    return {
        "id": d.id,
        "status": d.status,
        "chunk_count": d.chunk_count,
        "error": d.error_message,
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user["user_id"])
    )
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document not found")

    try:
        await delete_document_vectors(doc_id)
    except Exception:
        pass

    try:
        import os
        if d.storage_path and os.path.exists(d.storage_path):
            os.remove(d.storage_path)
    except Exception:
        pass

    await db.delete(d)
    await db.commit()
    return {"message": "Document deleted"}
