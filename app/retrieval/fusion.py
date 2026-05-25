from typing import List


def reciprocal_rank_fusion(
    dense_results: List[dict], sparse_results: List[dict], k: int = 60
) -> List[dict]:
    """Fuse dense + sparse rankings via RRF. Items keyed by (doc_id, chunk_index, text-prefix)."""
    def key(p: dict) -> str:
        pl = p["payload"]
        return f"{pl.get('doc_id','')}::{pl.get('chunk_index','')}::{pl['text'][:40]}"

    scores: dict[str, dict] = {}

    for rank, item in enumerate(dense_results):
        kk = key(item)
        scores.setdefault(kk, {"payload": item["payload"], "score": 0.0})
        scores[kk]["score"] += 1.0 / (k + rank + 1)

    for rank, item in enumerate(sparse_results):
        kk = key(item)
        scores.setdefault(kk, {"payload": item["payload"], "score": 0.0})
        scores[kk]["score"] += 1.0 / (k + rank + 1)

    return sorted(scores.values(), key=lambda x: x["score"], reverse=True)
