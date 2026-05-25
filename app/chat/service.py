"""End-to-end chat pipeline: detect lang → embed → dense+BM25 → RRF → LLM stream → persist."""
import time
import uuid
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.config import settings
from app.chat.models import ChatSession, Message
from app.chat.groq_client import stream_groq
from app.chat.prompt_builder import build_system_prompt, build_sources
from app.embeddings.embedder import embed_texts
from app.vector_store.store import dense_search
from app.retrieval.bm25 import bm25_search
from app.retrieval.fusion import reciprocal_rank_fusion
from app.documents.chunker import detect_language_safe


class ChatService:
    async def create_session(self, user_id: str, title: Optional[str], document_ids: Optional[list], db: AsyncSession) -> dict:
        s = ChatSession(
            user_id=user_id,
            title=title or "New conversation",
            document_ids=document_ids or [],
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return {
            "id": s.id,
            "title": s.title,
            "documentIds": s.document_ids or [],
            "createdAt": s.created_at.isoformat(),
        }

    async def list_sessions(self, user_id: str, db: AsyncSession) -> list:
        r = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(desc(ChatSession.updated_at))
            .limit(50)
        )
        return [
            {
                "id": s.id,
                "title": s.title,
                "language": s.language,
                "updatedAt": s.updated_at.isoformat(),
            }
            for s in r.scalars().all()
        ]

    async def get_messages(self, session_id: str, user_id: str, db: AsyncSession) -> list:
        r = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id
            )
        )
        if not r.scalar_one_or_none():
            return []

        mr = await db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        out = []
        for m in mr.scalars().all():
            out.append({
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "language": m.language,
                "sources": m.sources,
                "timestamp": m.created_at.isoformat() if m.created_at else None,
            })
        return out

    async def _ensure_session(self, session_id: Optional[str], user_id: str, db: AsyncSession) -> str:
        if session_id:
            r = await db.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id, ChatSession.user_id == user_id
                )
            )
            if r.scalar_one_or_none():
                return session_id
        # Create new session
        s = ChatSession(user_id=user_id, title="New conversation")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id

    async def _recent_history(self, session_id: str, db: AsyncSession, limit: int = 6) -> list:
        r = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        return [{"role": m.role, "content": m.content} for m in reversed(r.scalars().all())]

    async def process_query_stream(
        self,
        query: str,
        user_id: str,
        session_id: Optional[str],
        document_ids: Optional[list],
        db: AsyncSession,
    ) -> AsyncGenerator[dict, None]:
        t0 = time.time()
        try:
            session_id = await self._ensure_session(session_id, user_id, db)
            query_lang = detect_language_safe(query)

            # 1. Embed query
            qvecs = await embed_texts([query])
            qvec = qvecs[0]

            # 2. Dense retrieval
            dense_raw = await dense_search(
                query_vector=qvec,
                user_id=user_id,
                doc_ids=document_ids or None,
                top_k=settings.TOP_K_DENSE,
            )
            dense = [{"payload": r.payload, "dense_score": r.score} for r in dense_raw]

            # 3. BM25 over candidates
            sparse = bm25_search(query, query_lang, dense, top_k=settings.TOP_K_DENSE)

            # 4. RRF fusion
            fused = reciprocal_rank_fusion(dense, sparse)[: settings.TOP_K_FINAL]

            if not fused:
                msg = {
                    "en": "I couldn't find anything relevant in your documents.",
                    "ur": "مجھے آپ کے دستاویزات میں متعلقہ معلومات نہیں ملی۔",
                    "ar": "لم أعثر على معلومات ذات صلة في مستنداتك.",
                }.get(query_lang, "No relevant context found.")
                yield {"type": "sources", "data": []}
                yield {"type": "token", "data": msg}
                yield {"type": "done", "data": {"language": query_lang, "session_id": session_id}}
                # Save no-context exchange
                await self._save_exchange(session_id, query, msg, query_lang, [], 0, int((time.time() - t0) * 1000), db)
                return

            # 5. Emit sources
            sources = build_sources(fused)
            yield {"type": "sources", "data": sources}
            yield {"type": "session", "data": {"session_id": session_id}}

            # 6. Build prompt + stream
            system_prompt = build_system_prompt(fused)
            history = await self._recent_history(session_id, db, limit=6)
            messages = history + [{"role": "user", "content": query}]

            answer = ""
            async for tok in stream_groq(messages, system_prompt):
                answer += tok
                yield {"type": "token", "data": tok}

            latency = int((time.time() - t0) * 1000)
            await self._save_exchange(session_id, query, answer, query_lang, sources, len(answer.split()), latency, db)

            yield {"type": "done", "data": {"language": query_lang, "latency_ms": latency, "session_id": session_id}}
        except Exception as e:
            yield {"type": "error", "data": str(e)}

    async def _save_exchange(
        self, session_id, user_query, assistant_response, query_lang,
        sources, tokens_used, latency_ms, db
    ):
        db.add(Message(session_id=session_id, role="user", content=user_query, language=query_lang))
        db.add(Message(
            session_id=session_id, role="assistant", content=assistant_response,
            language=query_lang, sources=sources, tokens_used=tokens_used, latency_ms=latency_ms,
        ))
        r = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        sess = r.scalar_one_or_none()
        if sess:
            if sess.title == "New conversation":
                sess.title = user_query[:60]
            sess.language = query_lang
        await db.commit()


chat_service = ChatService()
