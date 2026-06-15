"""Embed product text docs and product images, storing vectors via sqlite-vec.

Usage:
  uv run python -m db.embed [--site SITE ...] [--modality text|image|both]
                             [--limit N] [--batch-size N] [--primary-only] [--dry-run]

`--limit N` selects the first N products (by id, per site) and embeds their
text docs plus *all* of their images (not a row-count limit on images).

`--primary-only` embeds just one representative image per product (is_primary,
falling back to lowest position/id) instead of every image.

Idempotent: a product/image is skipped if its current content hash matches
`embedding_state` AND a vector already exists for it. Images with identical
bytes (dedup across colors/variants) are embedded once and copied to every
sharing image_id.
"""

import argparse
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from db.connection import get_connection
from db.embeddings import GeminiEmbeddingProvider, SqliteVecStore
from db.embeddings.text_doc import build_text_doc

load_dotenv()

ROOT = Path(__file__).parent.parent
DIM = 768
COMMIT_EVERY = 50  # keep write transactions short so parallel processes don't starve each other
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_embedding_meta(con, modality: str, provider) -> None:
    con.execute(
        "INSERT OR IGNORE INTO embedding_meta (modality, model, dim, normalized, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (modality, provider.model_id, provider.dim, int(provider.normalized), datetime.now(timezone.utc).isoformat()),
    )


def _site_filter(query: str, sites: list[str] | None, params: list) -> str:
    if sites:
        query += f" AND site IN ({','.join('?' for _ in sites)})"
        params.extend(sites)
    return query


def _product_id_bounds(con, sites, limit) -> tuple[int, int] | None:
    """(min, max) id of the first `limit` products (by id, site-filtered)."""
    if not limit:
        return None
    params: list = []
    query = "SELECT id FROM product WHERE 1=1"
    query = _site_filter(query, sites, params)
    query += " ORDER BY id LIMIT ?"
    params.append(limit)
    ids = [r["id"] for r in con.execute(query, params).fetchall()]
    return (min(ids), max(ids)) if ids else None


def embed_text(con, provider, sites, limit, dry_run) -> None:
    store = SqliteVecStore(con, "vec_text", "product_id", provider.dim)

    params: list = []
    query = "SELECT id, name, description, brand, taxonomy_path FROM product WHERE 1=1"
    query = _site_filter(query, sites, params)
    query += " ORDER BY id"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    rows = con.execute(query, params).fetchall()

    todo = []  # (product_id, doc, hash)
    n_skipped = 0
    for row in rows:
        product_id = row["id"]
        attrs = con.execute(
            "SELECT name_raw, value_raw FROM attribute WHERE product_id = ?", (product_id,)
        ).fetchall()
        doc = build_text_doc(dict(row), [dict(a) for a in attrs])
        h = _hash(doc.encode("utf-8"))

        state = con.execute(
            "SELECT content_hash FROM embedding_state WHERE kind = 'text' AND ref_id = ?", (product_id,)
        ).fetchone()
        if state and state["content_hash"] == h and store.get(product_id) is not None:
            n_skipped += 1
            continue
        todo.append((product_id, doc, h))

    print(f"text: {len(rows)} products, {n_skipped} unchanged, {len(todo)} to embed")
    if dry_run or not todo:
        return

    _record_embedding_meta(con, "text", provider)
    con.commit()
    vectors = provider.embed_texts([doc for _, doc, _ in todo])
    for i, ((product_id, _, h), vec) in enumerate(zip(todo, vectors)):
        store.upsert(product_id, vec)
        con.execute(
            "INSERT OR REPLACE INTO embedding_state (kind, ref_id, content_hash) VALUES ('text', ?, ?)",
            (product_id, h),
        )
        if (i + 1) % COMMIT_EVERY == 0:
            con.commit()
    con.commit()
    print(f"text: embedded {len(todo)} products")


def embed_images(con, provider, sites, limit, dry_run, primary_only=False) -> None:
    store = SqliteVecStore(con, "vec_image", "image_id", provider.dim)

    params: list = []
    if primary_only:
        # one representative image per product: prefer is_primary, else lowest
        # position, else lowest id (some products have no is_primary=1 row).
        query = (
            "SELECT i.id, i.local_path, p.site FROM image i "
            "JOIN product p ON p.id = i.product_id WHERE i.id = ("
            "  SELECT i2.id FROM image i2 WHERE i2.product_id = i.product_id "
            "  ORDER BY i2.is_primary DESC, COALESCE(i2.position, 999999) ASC, i2.id ASC LIMIT 1"
            ")"
        )
    else:
        query = (
            "SELECT i.id, i.local_path, p.site FROM image i "
            "JOIN product p ON p.id = i.product_id WHERE 1=1"
        )
    query = _site_filter(query, sites, params)
    bounds = _product_id_bounds(con, sites, limit)
    if bounds:
        query += " AND i.product_id BETWEEN ? AND ?"
        params.extend(bounds)
    query += " ORDER BY i.id"
    rows = con.execute(query, params).fetchall()

    # groups: hash -> [image_id, ...] not yet embedded this run (one API call per hash)
    groups: dict[str, list[int]] = {}
    group_input: dict[str, tuple[bytes, str]] = {}
    to_copy: list[tuple[int, list[float], str]] = []  # (image_id, vector, hash) from a prior run's hash match
    n_skipped = 0
    n_missing = 0
    for row in rows:
        image_id, local_path, site = row["id"], row["local_path"], row["site"]
        if not local_path:
            n_missing += 1
            continue
        path = ROOT / "sites" / site / local_path.replace("\\", "/")
        if not path.exists():
            n_missing += 1
            continue

        data = path.read_bytes()
        h = _hash(data)

        state = con.execute(
            "SELECT content_hash FROM embedding_state WHERE kind = 'image' AND ref_id = ?", (image_id,)
        ).fetchone()
        if state and state["content_hash"] == h and store.get(image_id) is not None:
            n_skipped += 1
            continue

        if h in groups:
            groups[h].append(image_id)
            continue

        dup = con.execute(
            "SELECT ref_id FROM embedding_state WHERE kind = 'image' AND content_hash = ?", (h,)
        ).fetchone()
        if dup is not None:
            vec = store.get(dup["ref_id"])
            if vec is not None:
                to_copy.append((image_id, vec, h))
                continue

        mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
        groups[h] = [image_id]
        group_input[h] = (data, mime)

    n_to_embed = sum(len(ids) for ids in groups.values())
    print(
        f"image: {len(rows)} images, {n_skipped} unchanged, {len(to_copy)} deduped (copied), "
        f"{n_missing} missing locally, {n_to_embed} to embed ({len(groups)} unique)"
    )

    if not dry_run:
        for i, (image_id, vec, h) in enumerate(to_copy):
            store.upsert(image_id, vec)
            con.execute(
                "INSERT OR REPLACE INTO embedding_state (kind, ref_id, content_hash) VALUES ('image', ?, ?)",
                (image_id, h),
            )
            if (i + 1) % COMMIT_EVERY == 0:
                con.commit()
        con.commit()

    if dry_run or not groups:
        return

    _record_embedding_meta(con, "image", provider)
    con.commit()
    hashes = list(groups.keys())
    vectors = provider.embed_images([group_input[h] for h in hashes])
    n_embedded = 0
    for i, (h, vec) in enumerate(zip(hashes, vectors)):
        for image_id in groups[h]:
            store.upsert(image_id, vec)
            con.execute(
                "INSERT OR REPLACE INTO embedding_state (kind, ref_id, content_hash) VALUES ('image', ?, ?)",
                (image_id, h),
            )
            n_embedded += 1
        if (i + 1) % COMMIT_EVERY == 0:
            con.commit()
    con.commit()
    print(f"image: embedded {n_embedded} images ({len(groups)} API inputs)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="append", dest="sites", choices=["panhome", "homecentre", "homesrus"])
    parser.add_argument("--modality", choices=["text", "image", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--primary-only", action="store_true",
        help="embed only one representative image per product (is_primary, else lowest position/id)",
    )
    args = parser.parse_args(argv)

    con = get_connection()
    con.row_factory = sqlite3.Row
    provider = GeminiEmbeddingProvider(dim=DIM, batch_size=args.batch_size)

    if args.modality in ("text", "both"):
        embed_text(con, provider, args.sites, args.limit, args.dry_run)
    if args.modality in ("image", "both"):
        embed_images(con, provider, args.sites, args.limit, args.dry_run, args.primary_only)

    con.close()


if __name__ == "__main__":
    main()
