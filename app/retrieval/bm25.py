from typing import List
from rank_bm25 import BM25Okapi
import re


_ARABIC_RANGE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]+|[\w']+")
_WORD = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str, lang: str = "en") -> List[str]:
    text = (text or "").lower()
    if lang in {"ar", "ur", "fa"}:
        return [t for t in _ARABIC_RANGE.findall(text) if t.strip()]
    return _WORD.findall(text)


def bm25_search(query: str, query_lang: str, corpus: List[dict], top_k: int = 20) -> List[dict]:
    """Re-rank a candidate corpus using BM25. Each item has 'payload.text'."""
    if not corpus:
        return []

    texts = [c["payload"]["text"] for c in corpus]
    tokenized_corpus = [_tokenize(t, c["payload"].get("lang", "en")) for t, c in zip(texts, corpus)]
    bm25 = BM25Okapi(tokenized_corpus)
    tokenized_query = _tokenize(query, query_lang)
    scores = bm25.get_scores(tokenized_query)

    ranked = sorted(
        [
            {"payload": c["payload"], "sparse_score": float(s)}
            for c, s in zip(corpus, scores)
        ],
        key=lambda x: x["sparse_score"],
        reverse=True,
    )
    return ranked[:top_k]
