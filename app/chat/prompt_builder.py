from typing import List


SYSTEM_TEMPLATE = """You are LingualRAG, a multilingual assistant. Answer the user's question using ONLY the context below. Reply in the same language the user used.

Rules:
- Cite sources inline as [1], [2], … matching the order shown.
- If the answer is not in the context, say so honestly.
- Be concise and accurate.

[CONTEXT]
{context}
"""


def build_system_prompt(reranked: List[dict]) -> str:
    blocks = []
    for i, item in enumerate(reranked, 1):
        pl = item["payload"]
        head = f"[{i}] (page {pl.get('page', '?')}, file {pl.get('filename', '?')}, lang {pl.get('lang','?')})"
        blocks.append(f"{head}\n{pl['text']}")
    context = "\n\n".join(blocks) if blocks else "(no documents retrieved)"
    return SYSTEM_TEMPLATE.format(context=context)


def build_sources(reranked: List[dict]) -> list:
    out = []
    for i, item in enumerate(reranked, 1):
        pl = item["payload"]
        text = pl["text"]
        excerpt = text if len(text) <= 280 else text[:280] + "…"
        out.append({
            "id": f"src-{i}",
            "title": f"{pl.get('filename', 'doc')} (p.{pl.get('page', 1)})",
            "excerpt": excerpt,
            "relevance": round(float(item.get("score", 0.0)), 4),
            "doc_id": pl.get("doc_id"),
            "page": pl.get("page"),
            "lang": pl.get("lang"),
        })
    return out
