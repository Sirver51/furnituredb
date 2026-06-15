"""Normalizer for sites/homecentre/raw/products/<pid>.json.

Each file holds the FULL parent+variants record regardless of which color's
pid triggered the fetch, so multiple files share the same top-level `id`
(ULID) — dedupe on that. One product row per color variant; group_key is
always the parent ULID.
"""

import re
from pathlib import Path
from typing import Iterator

from .common import base_product, clean_html, content_hash, file_crawled_at, load_image_manifest, load_json_bytes

SITE = "homecentre"

COLOR_TAG_RE = re.compile(r"^color:(.+)$")


def _assets_by_color(assets: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    by_color: dict[str, list[dict]] = {}
    shared: list[dict] = []
    for asset in assets or []:
        if asset.get("type") != "IMAGE":
            continue
        color_skus = []
        for tag in asset.get("tags") or []:
            m = COLOR_TAG_RE.match(tag)
            if m:
                color_skus.append(m.group(1))
        if color_skus:
            for sku in color_skus:
                by_color.setdefault(sku, []).append(asset)
        else:
            shared.append(asset)
    return by_color, shared


def _images_for_variant(sku: str, by_color: dict[str, list[dict]], shared: list[dict],
                         image_manifest: dict[str, str]) -> list[dict]:
    assets = by_color.get(sku) or shared
    images = []
    for i, asset in enumerate(assets):
        url = asset.get("url") or asset.get("contentUrl")
        if not url:
            continue
        images.append({
            "url": url,
            "local_path": image_manifest.get(url),
            "position": i,
            "is_primary": 1 if asset.get("primary") else 0,
            "color_tag": f"color:{sku}" if sku in by_color else None,
        })
    return images


def _availability(data: dict) -> str:
    if data.get("active") and data.get("online") and data.get("availableOnline") and not data.get("discontinued"):
        return "InStock"
    return "OutOfStock"


def iter_products(site_dir: Path) -> Iterator[dict]:
    image_manifest = load_image_manifest(site_dir)
    products_dir = site_dir / "raw" / "products"
    root = site_dir.parent.parent

    seen_group_ids: set[str] = set()

    for path in sorted(products_dir.glob("*/*.json")):
        data, raw_bytes = load_json_bytes(path)
        group_id = data["id"]
        if group_id in seen_group_ids:
            continue
        seen_group_ids.add(group_id)

        raw_path_str = str(path.relative_to(root)).replace("\\", "/")
        crawled_at = file_crawled_at(path)
        hash_ = content_hash(raw_bytes)

        description = clean_html(data.get("description"))
        brand = (data.get("brand") or {}).get("displayValue")
        uri = data.get("uri")
        url = f"https://www.homecentre.com/ae/en{uri}" if uri else None
        availability = _availability(data)

        breadcrumbs = data.get("breadcrumbs") or []
        taxonomy_path = "/".join(b["label"] for b in breadcrumbs[:-1]) if len(breadcrumbs) > 1 else None

        attributes = [
            {"name_raw": a["nameLabel"], "value_raw": str(a["value"])}
            for a in (data.get("attributes") or [])
            if a.get("value") not in (None, "")
        ]

        by_color, shared = _assets_by_color(data.get("assets") or [])

        for variant in data.get("variants") or []:
            sku = variant.get("sku")
            if not sku:
                continue
            rec = base_product()
            rec["site"] = SITE
            rec["source_id"] = sku
            rec["source_key"] = path.stem
            rec["group_key"] = group_id
            rec["sku"] = sku
            rec["name"] = data.get("name", "").strip()
            rec["description"] = description
            rec["brand"] = brand
            rec["url"] = url
            rec["raw_path"] = raw_path_str
            rec["content_hash"] = hash_
            rec["crawled_at"] = crawled_at
            rec["availability"] = availability
            rec["taxonomy_path"] = taxonomy_path

            default_price = variant.get("defaultPrice") or {}
            sale_price = variant.get("salePrice")
            rec["currency"] = default_price.get("currency", data.get("currency", "AED"))
            rec["regular_price"] = default_price.get("amount")
            if sale_price and sale_price.get("amount") is not None:
                rec["price"] = sale_price["amount"]
                if rec["regular_price"]:
                    rec["discount_pct"] = round(
                        (rec["regular_price"] - rec["price"]) / rec["regular_price"] * 100, 3
                    )
            else:
                rec["price"] = rec["regular_price"]

            rec["_attributes"] = attributes
            rec["_images"] = _images_for_variant(sku, by_color, shared, image_manifest)

            yield rec
