"""Read-only product/image/neighbor accessors over furniture.db."""

from __future__ import annotations

import sqlite3

from db.embeddings.store import SqliteVecStore
from web.search import DIM, cosine_similarity


def get_card(con: sqlite3.Connection, product_id: int) -> dict | None:
    """Minimal fields for a result-grid card / graph node."""
    row = con.execute(
        "SELECT id, name, price, currency, site, taxonomy_path FROM product WHERE id = ?",
        (product_id,),
    ).fetchone()
    if row is None:
        return None
    card = dict(row)
    img = con.execute(
        "SELECT id FROM image WHERE product_id = ? ORDER BY is_primary DESC, position LIMIT 1",
        (product_id,),
    ).fetchone()
    card["image_id"] = img[0] if img else None
    return card


def get_cards(
    con: sqlite3.Connection,
    ids: list[int],
    site: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    similarities: dict[int, float] | None = None,
) -> list[dict]:
    """Hydrate an ordered list of product ids into cards, applying filters.

    Filters are applied post-fusion: ids that don't match are dropped (not
    backfilled), so the result count can be < len(ids) when filters are tight.

    `similarities` maps product id -> cosine similarity (-1..1) to the query
    vector; attached to each card as `similarity` (a 0-100 percentage), or
    `None` if no vector match was found for that id.
    """
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    query = f"SELECT id, name, price, currency, site, taxonomy_path FROM product WHERE id IN ({placeholders})"
    params: list = list(ids)
    if site:
        query += " AND site = ?"
        params.append(site)
    if price_min is not None:
        query += " AND price >= ?"
        params.append(price_min)
    if price_max is not None:
        query += " AND price <= ?"
        params.append(price_max)

    rows = {row["id"]: dict(row) for row in con.execute(query, params)}

    cards = []
    for pid in ids:
        row = rows.get(pid)
        if row is None:
            continue
        img = con.execute(
            "SELECT id FROM image WHERE product_id = ? ORDER BY is_primary DESC, position LIMIT 1",
            (pid,),
        ).fetchone()
        row["image_id"] = img[0] if img else None
        sim = similarities.get(pid) if similarities else None
        row["similarity"] = round(sim * 100, 1) if sim is not None else None
        cards.append(row)
    return cards


def get_product(con: sqlite3.Connection, product_id: int) -> dict | None:
    row = con.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        return None

    product = dict(row)
    product["attributes"] = [
        dict(r)
        for r in con.execute(
            "SELECT name_raw, name_canonical, value_raw, value_canonical, unit "
            "FROM attribute WHERE product_id = ?",
            (product_id,),
        )
    ]
    product["images"] = [
        dict(r)
        for r in con.execute(
            "SELECT id, url, local_path, position, is_primary, color_tag "
            "FROM image WHERE product_id = ? ORDER BY is_primary DESC, position",
            (product_id,),
        )
    ]
    if product["group_key"]:
        product["variants"] = [
            dict(r)
            for r in con.execute(
                "SELECT id, sku, name, price, currency, is_group_parent FROM product "
                "WHERE site = ? AND group_key = ? AND id != ? ORDER BY name",
                (product["site"], product["group_key"], product_id),
            )
        ]
    else:
        product["variants"] = []

    return product


def _weight(distance: float) -> float:
    """Map a vec0 distance to a similarity-like edge weight in (0, 1]."""
    return 1.0 / (1.0 + max(distance, 0.0))


def neighbors(con: sqlite3.Connection, product_id: int, mode: str, k: int = 12) -> dict:
    """Nodes/edges for the graph view: nearest products by `mode`'s vector space."""
    center = get_card(con, product_id)
    if center is None:
        return {"center": None, "nodes": [], "edges": [], "available": False}

    if mode == "semantic":
        store = SqliteVecStore(con, "vec_text", "product_id", DIM)
        vec = store.get(product_id)
        if vec is None:
            return {"center": center, "nodes": [], "edges": [], "available": False}

        hits = [(pid, dist) for pid, dist in store.search(vec, k + 1) if pid != product_id][:k]
        nodes = get_cards(con, [pid for pid, _ in hits])
        edges = [
            {"source": product_id, "target": pid, "weight": _weight(dist), "similarity": round(cosine_similarity(dist) * 100, 1)}
            for pid, dist in hits
        ]

    elif mode == "visual":
        store = SqliteVecStore(con, "vec_image", "image_id", DIM)
        primary = con.execute(
            "SELECT id FROM image WHERE product_id = ? ORDER BY is_primary DESC, position LIMIT 1",
            (product_id,),
        ).fetchone()
        if primary is None:
            return {"center": center, "nodes": [], "edges": [], "available": False}

        vec = store.get(primary["id"])
        if vec is None:
            return {"center": center, "nodes": [], "edges": [], "available": False}

        # Over-fetch images, then collapse to best-distance-per-product (excluding self).
        hits = [(iid, dist) for iid, dist in store.search(vec, (k + 1) * 3) if iid != primary["id"]]
        best: dict[int, float] = {}
        for image_id, dist in hits:
            row = con.execute("SELECT product_id FROM image WHERE id = ?", (image_id,)).fetchone()
            if row is None or row[0] == product_id:
                continue
            pid = row[0]
            if pid not in best or dist < best[pid]:
                best[pid] = dist

        top = sorted(best.items(), key=lambda kv: kv[1])[:k]
        nodes = get_cards(con, [pid for pid, _ in top])
        edges = [
            {"source": product_id, "target": pid, "weight": _weight(dist), "similarity": round(cosine_similarity(dist) * 100, 1)}
            for pid, dist in top
        ]

    else:
        raise ValueError(f"unknown neighbor mode: {mode!r}")

    return {"center": center, "nodes": nodes, "edges": edges, "available": True}
