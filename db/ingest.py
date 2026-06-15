"""Ingest raw/products/**/*.json for one or more sites into the normalized DB.

Usage: uv run python -m db.ingest [site ...]
Idempotent: products whose content_hash is unchanged are skipped entirely.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from db.connection import get_connection
from db.normalize import NORMALIZERS

ROOT = Path(__file__).parent.parent

PRODUCT_COLUMNS = [
    "site", "source_id", "source_key", "group_key", "is_group_parent", "sku", "name",
    "description", "brand", "url", "currency", "price", "regular_price", "discount_pct",
    "availability", "rating_value", "rating_count", "taxonomy_path", "raw_path",
    "content_hash", "crawled_at",
]


def upsert_product(con, rec: dict) -> tuple[int, bool]:
    existing = con.execute(
        "SELECT id, content_hash FROM product WHERE site = ? AND source_id = ?",
        (rec["site"], rec["source_id"]),
    ).fetchone()
    if existing and existing[1] == rec["content_hash"]:
        return existing[0], False

    values = [rec[c] for c in PRODUCT_COLUMNS]
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        product_id = existing[0]
        set_clause = ", ".join(f"{c} = ?" for c in PRODUCT_COLUMNS)
        con.execute(
            f"UPDATE product SET {set_clause}, ingested_at = ? WHERE id = ?",
            (*values, now, product_id),
        )
        con.execute("DELETE FROM image WHERE product_id = ?", (product_id,))
        con.execute("DELETE FROM attribute WHERE product_id = ?", (product_id,))
    else:
        placeholders = ", ".join("?" for _ in PRODUCT_COLUMNS)
        cur = con.execute(
            f"INSERT INTO product ({', '.join(PRODUCT_COLUMNS)}, ingested_at) VALUES ({placeholders}, ?)",
            (*values, now),
        )
        product_id = cur.lastrowid

    for img in rec["_images"]:
        con.execute(
            "INSERT OR IGNORE INTO image (product_id, url, local_path, position, is_primary, color_tag) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (product_id, img["url"], img["local_path"], img["position"], img["is_primary"], img["color_tag"]),
        )

    for attr in rec["_attributes"]:
        con.execute(
            "INSERT INTO attribute (product_id, name_raw, value_raw) VALUES (?, ?, ?)",
            (product_id, attr["name_raw"], attr["value_raw"]),
        )

    specs_text = "; ".join(f"{a['name_raw']}: {a['value_raw']}" for a in rec["_attributes"])
    con.execute("DELETE FROM product_fts WHERE rowid = ?", (product_id,))
    con.execute(
        "INSERT INTO product_fts (rowid, name, description, specs) VALUES (?, ?, ?, ?)",
        (product_id, rec["name"], rec["description"], specs_text),
    )

    return product_id, True


def ingest_site(con, site: str) -> None:
    normalizer = NORMALIZERS[site]
    site_dir = ROOT / "sites" / site
    n_total = n_changed = n_images = 0

    for rec in normalizer.iter_products(site_dir):
        n_total += 1
        _, changed = upsert_product(con, rec)
        if changed:
            n_changed += 1
            n_images += len(rec["_images"])
        if n_total % 1000 == 0:
            con.commit()
            print(f"  {site}: {n_total} processed ({n_changed} new/changed)...")

    con.commit()
    print(f"{site}: {n_total} products processed, {n_changed} new/changed, {n_images} image refs")


def main(argv: list[str]) -> None:
    sites = argv or list(NORMALIZERS.keys())
    con = get_connection()
    for site in sites:
        ingest_site(con, site)
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
