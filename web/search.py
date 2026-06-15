"""Hybrid search: FTS5 BM25 + sqlite-vec KNN (text and/or image), fused with RRF.

Reuses db.embeddings.{provider,store} read-only -- same Gemini Embedding 2
space (dim=768) the ingestion/embedding pipeline writes to. Degrades to
FTS-only when vec_text/vec_image are empty or the embedding provider is
unavailable (e.g. missing GEMINI_API_KEY), so search works before/without
embeddings being populated.
"""

from __future__ import annotations

import re
import sqlite3

from db.embeddings.provider import GeminiEmbeddingProvider
from db.embeddings.store import SqliteVecStore

DIM = 768
RRF_K = 60


def _fts_query(q: str) -> str | None:
    """Turn free text into an FTS5 MATCH expression: quoted terms OR'd together."""
    terms = re.findall(r"\w+", q)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def cosine_similarity(distance: float) -> float:
    """Cosine similarity from a sqlite-vec L2 distance, for unit-normalized vectors.

    For unit vectors, ||a-b||^2 = 2 - 2*cos(a,b), so cos(a,b) = 1 - distance^2/2.
    """
    return max(-1.0, min(1.0, 1.0 - (distance**2) / 2.0))


def rrf_fuse(rank_lists: list[list[int]], k: int = RRF_K) -> list[int]:
    """Reciprocal Rank Fusion: combine multiple id rankings into one."""
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, item_id in enumerate(ranks):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


class SearchService:
    def __init__(self, con: sqlite3.Connection):
        self._con = con
        self._vec_text = SqliteVecStore(con, "vec_text", "product_id", DIM)
        self._vec_image = SqliteVecStore(con, "vec_image", "image_id", DIM)
        self._provider: GeminiEmbeddingProvider | None = None
        self._provider_error: str | None = None

    def embeddings_available(self) -> dict[str, int]:
        text = self._con.execute("SELECT COUNT(*) FROM vec_text").fetchone()[0]
        image = self._con.execute("SELECT COUNT(*) FROM vec_image").fetchone()[0]
        return {"text": text, "image": image}

    def _get_provider(self) -> GeminiEmbeddingProvider | None:
        if self._provider is not None:
            return self._provider
        if self._provider_error:
            return None
        try:
            self._provider = GeminiEmbeddingProvider(dim=DIM)
        except Exception as exc:
            self._provider_error = str(exc)
            return None
        return self._provider

    def _fts_search(self, q: str, k: int) -> list[int]:
        fts_q = _fts_query(q)
        if not fts_q:
            return []
        rows = self._con.execute(
            "SELECT rowid FROM product_fts WHERE product_fts MATCH ? ORDER BY bm25(product_fts) LIMIT ?",
            (fts_q, k),
        ).fetchall()
        return [r[0] for r in rows]

    def _image_hits_to_products(self, img_hits: list[tuple[int, float]]) -> tuple[list[int], dict[int, float]]:
        """Map vec_image (image_id, distance) hits to deduped product ids (rank order) + per-product similarity."""
        seen: set[int] = set()
        product_ids: list[int] = []
        similarities: dict[int, float] = {}
        for image_id, dist in img_hits:
            row = self._con.execute("SELECT product_id FROM image WHERE id = ?", (image_id,)).fetchone()
            if row is None:
                continue
            pid = row[0]
            sim = cosine_similarity(dist)
            if pid not in seen:
                seen.add(pid)
                product_ids.append(pid)
                similarities[pid] = sim
            else:
                similarities[pid] = max(similarities[pid], sim)
        return product_ids, similarities

    def search_text(self, q: str, k: int = 40) -> tuple[list[int], dict, dict[int, float]]:
        rank_lists = [self._fts_search(q, k * 3)]
        info: dict = {"lexical": len(rank_lists[0]), "semantic": 0, "cross_modal": 0}
        similarities: dict[int, float] = {}

        avail = self.embeddings_available()
        if avail["text"] > 0 or avail["image"] > 0:
            provider = self._get_provider()
            if provider is None:
                info["semantic_error"] = self._provider_error
            else:
                try:
                    qvec = provider.embed_texts([q])[0]

                    if avail["text"] > 0:
                        hits = self._vec_text.search(qvec, min(k * 3, avail["text"]))
                        rank_lists.append([pid for pid, _ in hits])
                        info["semantic"] = len(rank_lists[-1])
                        for pid, dist in hits:
                            sim = cosine_similarity(dist)
                            similarities[pid] = max(similarities.get(pid, sim), sim)

                    if avail["image"] > 0:
                        img_hits = self._vec_image.search(qvec, min(k * 5, avail["image"]))
                        cross_ids, cross_sims = self._image_hits_to_products(img_hits)
                        rank_lists.append(cross_ids)
                        info["cross_modal"] = len(cross_ids)
                        for pid, sim in cross_sims.items():
                            similarities[pid] = max(similarities.get(pid, sim), sim)
                except Exception as exc:
                    info["semantic_error"] = str(exc)

        return rrf_fuse(rank_lists)[:k], info, similarities

    def search_image(self, image_bytes: bytes, mime: str, k: int = 40) -> tuple[list[int], dict, dict[int, float]]:
        provider = self._get_provider()
        if provider is None:
            return [], {"error": self._provider_error or "embedding provider unavailable"}, {}

        avail = self.embeddings_available()
        if avail["text"] == 0 and avail["image"] == 0:
            return [], {"error": "no embeddings indexed yet"}, {}

        try:
            qvec = provider.embed_images([(image_bytes, mime)])[0]
        except Exception as exc:
            return [], {"error": str(exc)}, {}

        rank_lists: list[list[int]] = []
        info: dict = {"visual": 0, "cross_modal": 0}
        similarities: dict[int, float] = {}

        if avail["image"] > 0:
            img_hits = self._vec_image.search(qvec, min(k * 5, avail["image"]))
            visual_ids, visual_sims = self._image_hits_to_products(img_hits)
            rank_lists.append(visual_ids)
            info["visual"] = len(visual_ids)
            for pid, sim in visual_sims.items():
                similarities[pid] = max(similarities.get(pid, sim), sim)

        if avail["text"] > 0:
            hits = self._vec_text.search(qvec, min(k * 3, avail["text"]))
            rank_lists.append([pid for pid, _ in hits])
            info["cross_modal"] = len(rank_lists[-1])
            for pid, dist in hits:
                sim = cosine_similarity(dist)
                similarities[pid] = max(similarities.get(pid, sim), sim)

        return rrf_fuse(rank_lists)[:k], info, similarities
