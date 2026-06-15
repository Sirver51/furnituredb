"""Normalizer for sites/homesrus/raw/products/<sku>.json.

No variant grouping: every color/size is its own standalone record.
"""

from pathlib import Path
from typing import Iterator

from .common import base_product, content_hash, file_crawled_at, load_image_manifest, load_json_bytes

SITE = "homesrus"


def iter_products(site_dir: Path) -> Iterator[dict]:
    image_manifest = load_image_manifest(site_dir)
    products_dir = site_dir / "raw" / "products"

    for path in sorted(products_dir.glob("*/*.json")):
        data, raw_bytes = load_json_bytes(path)
        rec = base_product()

        rec["site"] = SITE
        rec["source_id"] = data["sku"]
        rec["source_key"] = path.stem
        rec["sku"] = data["sku"]
        rec["name"] = data.get("name", "").strip()
        rec["description"] = data.get("description")
        rec["brand"] = (data.get("brand") or {}).get("name")
        rec["url"] = data.get("url")
        rec["raw_path"] = str(path.relative_to(site_dir.parent.parent)).replace("\\", "/")
        rec["content_hash"] = content_hash(raw_bytes)
        rec["crawled_at"] = file_crawled_at(path)

        offers = data.get("offers") or {}
        rec["currency"] = offers.get("priceCurrency", "AED")
        rec["price"] = offers.get("price")
        availability = offers.get("availability")
        if availability:
            rec["availability"] = availability.rsplit("/", 1)[-1]

        rating = data.get("aggregateRating")
        if rating:
            try:
                rec["rating_value"] = float(rating.get("ratingValue"))
            except (TypeError, ValueError):
                pass
            try:
                rec["rating_count"] = int(rating.get("ratingCount"))
            except (TypeError, ValueError):
                pass

        breadcrumbs = data.get("breadcrumbs") or []
        if len(breadcrumbs) > 1:
            rec["taxonomy_path"] = "/".join(b["name"] for b in breadcrumbs[:-1])

        for key, value in (data.get("specs") or {}).items():
            rec["_attributes"].append({"name_raw": key, "value_raw": str(value)})

        gallery = data.get("gallery") or []
        primary_url = data.get("image")
        for i, url in enumerate(gallery):
            rec["_images"].append({
                "url": url,
                "local_path": image_manifest.get(url),
                "position": i,
                "is_primary": 1 if (url == primary_url or i == 0) else 0,
                "color_tag": None,
            })

        yield rec
