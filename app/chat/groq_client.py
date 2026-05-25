"""Groq streaming client with an extractive fallback (no internet required)."""
from typing import AsyncGenerator, List
import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and settings.GROQ_API_KEY:
        from groq import AsyncGroq
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


async def stream_groq(
    messages: List[dict], system_prompt: str
) -> AsyncGenerator[str, None]:
    """
    Stream tokens from Groq. If GROQ_API_KEY is missing, fall back to an
    extractive summary of the system prompt's context so the full pipeline
    is still demonstrable.
    """
    client = _get_client()

    if client is None:
        # Fallback: emit a deterministic answer based on retrieved context.
        async for chunk in _extractive_fallback(messages, system_prompt):
            yield chunk
        return

    try:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        completion = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=full_messages,
            stream=True,
            temperature=0.3,
            max_tokens=1500,
        )
        async for chunk in completion:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as e:
        logger.warning("Groq streaming failed (%s) — using extractive fallback.", e)
        async for chunk in _extractive_fallback(messages, system_prompt):
            yield chunk


async def _extractive_fallback(messages: List[dict], system_prompt: str) -> AsyncGenerator[str, None]:
    """Build a simple grounded answer by quoting retrieved context."""
    user_q = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    # Pull the [CONTEXT] block out of the system prompt
    context_block = ""
    marker = "[CONTEXT]"
    if marker in system_prompt:
        context_block = system_prompt.split(marker, 1)[1]
    snippets = []
    for line in context_block.splitlines():
        s = line.strip()
        if s and not s.startswith("[") and not s.startswith("Source"):
            snippets.append(s)
        if len(snippets) >= 4:
            break

    answer = f"Based on the retrieved documents, here is what I found regarding: \"{user_q}\".\n\n"
    if snippets:
        for i, s in enumerate(snippets, 1):
            answer += f"{i}. {s[:300]}\n"
    else:
        answer = "I could not find specific information in the retrieved documents to answer this question."

    # Stream it in small chunks to mimic LLM streaming
    for i in range(0, len(answer), 12):
        await asyncio.sleep(0.01)
        yield answer[i:i + 12]
