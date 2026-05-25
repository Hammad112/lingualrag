import json
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, AsyncSessionLocal
from app.middleware.auth_middleware import get_current_user
from app.chat.service import chat_service
from app.chat.models import Message

router = APIRouter()


class NewSessionRequest(BaseModel):
    title: Optional[str] = None
    document_ids: Optional[List[str]] = None


class StreamRequest(BaseModel):
    query: Optional[str] = None
    message: Optional[str] = None       # alias used by frontend
    session_id: Optional[str] = None
    sessionId: Optional[str] = None     # camelCase alias
    document_ids: Optional[List[str]] = None
    documentIds: Optional[List[str]] = None


class ChatMessageRequest(BaseModel):
    sessionId: Optional[str] = None
    message: str


@router.post("/sessions")
async def create_session(
    req: NewSessionRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat_service.create_session(
        current_user["user_id"], req.title, req.document_ids, db
    )


@router.get("/sessions")
async def list_sessions(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"sessions": await chat_service.list_sessions(current_user["user_id"], db)}


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages = await chat_service.get_messages(session_id, current_user["user_id"], db)
    return {"messages": messages}


async def _stream(query: str, user_id: str, session_id: Optional[str], document_ids: Optional[List[str]]):
    async with AsyncSessionLocal() as db:
        async for event in chat_service.process_query_stream(
            query=query,
            user_id=user_id,
            session_id=session_id,
            document_ids=document_ids,
            db=db,
        ):
            # Frontend useChat expects {type: 'chunk', content} for tokens
            # and {type: 'done', sources} when finished. Translate.
            if event["type"] == "token":
                payload = {"type": "chunk", "content": event["data"]}
            elif event["type"] == "sources":
                payload = {"type": "sources", "sources": event["data"]}
            elif event["type"] == "session":
                payload = {"type": "session", "sessionId": event["data"]["session_id"]}
            elif event["type"] == "done":
                payload = {"type": "done", **event["data"]}
            elif event["type"] == "error":
                payload = {"type": "error", "error": event["data"]}
            else:
                payload = event
            yield f"data: {json.dumps(payload)}\n\n"


@router.post("/stream")
async def stream_post(
    req: StreamRequest,
    current_user: dict = Depends(get_current_user),
):
    query = req.query or req.message
    if not query:
        raise HTTPException(400, "Missing query")
    sid = req.session_id or req.sessionId
    docs = req.document_ids or req.documentIds
    return StreamingResponse(
        _stream(query, current_user["user_id"], sid, docs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/message")
async def chat_message(
    req: ChatMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Non-streaming single-shot version (used by some frontend code paths)."""
    last_content, all_sources, lang = "", [], None
    sid = req.sessionId
    async for event in chat_service.process_query_stream(
        query=req.message, user_id=current_user["user_id"],
        session_id=sid, document_ids=None, db=db,
    ):
        if event["type"] == "token":
            last_content += event["data"]
        elif event["type"] == "sources":
            all_sources = event["data"]
        elif event["type"] == "session":
            sid = event["data"]["session_id"]
        elif event["type"] == "done":
            lang = event["data"].get("language")
    return {
        "content": last_content,
        "sources": all_sources,
        "language": lang,
        "sessionId": sid,
    }


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.chat.models import ChatSession

    r = await db.execute(
        select(Message).join(ChatSession, Message.session_id == ChatSession.id)
        .where(Message.id == message_id, ChatSession.user_id == current_user["user_id"])
    )
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Message not found")
    await db.delete(m)
    await db.commit()
    return {"message": "Deleted"}
