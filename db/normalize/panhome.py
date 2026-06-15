"""Normalizer for sites/panhome/raw/products/<id>.json.

Configurable parent + variants[] (each a full nested product, also sometimes
present as its own top-level file). We yield a row for the parent
(is_group_parent=1) AND for each nested variant (group_key=parent id), plus
every standalone top-level file (group_key resolved from the configurable
parents seen during the same pass, else NULL).
"""

import json
from pathlib import Path
from typing import Iterator

from .common import base_product, clean_html, content_hash, file_crawled_at, load_image_manifest, load_json_bytes

SITE = "panhome"

# Magento/internal attribute codes with no retrieval value.
ATTR_BLOCKLIST = {
    "name", "price", "special_price", "image", "small_image", "thumbnail",
    "status", "required_options", "msrp_display_actual_price_type", "url_key",
    "swatch_image", "tax_class_id", "bundle_thumbnail", "product_price_type",
    "discount_range", "hullabalook_visibility", "is_pan_bloom", "price_Range",
    "offer_sample",
}

# Category-name keywords marking promotional/cross-listing rollups (handoff
# doc: categories[] is polluted with these alongside the real taxonomy).
PROMO_KEYWORDS = (
    "sale", "discount", "offer", "new arrival", "last chance", "above 999",
    "shop by", "flat ", "biggest price drop", "best price",
)


def _is_promo_path(names: list[str]) -> bool:
    joined = " ".join(names).lower()
    return any(kw in joined for kw in PROMO_KEYWORDS)


def _taxonomy_path(categories: list[dict]) -> str | None:
    best: list[str] | None = None
    for cat in categories or []:
        breadcrumbs = cat.get("breadcrumbs") or []
        path = [b["category_name"] for b in breadcrumbs] + [cat["name"]]
        if _is_promo_path(path):
            continue
        if best is None or len(path) > len(best):
            best = path
    return "/".join(p.strip() for p in best) if best else None


def _extract_attributes(attributes: list[dict]) -> tuple[list[dict], str | None]:
    out = []
    brand = None
    for attr in attributes or []:
        code = attr.get("attribute_code")
        if code in ATTR_BLOCKLIST or attr.get("attribute_type") == "media_image":
            continue
        value = attr.get("attribute_value")
        if value in (None, "", "no_selection"):
            continue
        options = attr.get("attribute_options") or []
        if options:
            value_raw = "; ".join(o["label"] for o in options if o.get("label"))
        else:
            value_raw = str(value)
        if not value_raw:
            continue
        name_raw = attr.get("attribute_label") or code
        out.append({"name_raw": name_raw, "value_raw": value_raw})
        if code in ("brand", "manufacturer"):
            brand = value_raw
    return out, brand


def _extract_images(media_gallery_entries: list[dict], image_manifest: dict[str, str]) -> list[dict]:
    images = []
    for entry in media_gallery_entries or []:
        url = (entry.get("base") or {}).get("url")
        if not url:
            continue
        position = entry.get("position", 0)
        images.append({
            "url": url,
            "local_path": image_manifest.get(url),
            "position": position,
            "is_primary": 1 if position == 1 else 0,
            "color_tag": None,
        })
    return images


def _normalize_one(data: dict, *, source_key: str, raw_path_str: str, raw_bytes: bytes | None,
                    crawled_at: str, group_key: str | None, is_group_parent: bool,
                    image_manifest: dict[str, str]) -> dict:
    rec = base_product()
    rec["site"] = SITE
    rec["source_id"] = str(data["id"])
    rec["source_key"] = source_key
    rec["group_key"] = group_key
    rec["is_group_parent"] = 1 if is_group_parent else 0
    rec["sku"] = data.get("sku")
    rec["name"] = data.get("name", "").strip()
    rec["raw_path"] = raw_path_str
    rec["content_hash"] = content_hash(raw_bytes) if raw_bytes is not None else content_hash(
        json.dumps(data, sort_keys=True).encode("utf-8")
    )
    rec["crawled_at"] = crawled_at

    description = clean_html((data.get("description") or {}).get("html"))
    rec["description"] = description or data.get("meta_description")

    price_range = data.get("price_range") or {}
    min_price = price_range.get("minimum_price") or {}
    final_price = min_price.get("final_price") or {}
    regular_price = min_price.get("regular_price") or {}
    discount = min_price.get("discount") or {}
    rec["currency"] = final_price.get("currency", "AED")
    rec["price"] = final_price.get("value")
    rec["regular_price"] = regular_price.get("value")
    rec["discount_pct"] = discount.get("percent_off")

    rec["availability"] = data.get("stock_status")
    if data.get("review_count"):
        rec["rating_value"] = data.get("rating_summary")
        rec["rating_count"] = data.get("review_count")

    rec["url"] = (data.get("mw_canonical_url") or {}).get("url")
    rec["taxonomy_path"] = _taxonomy_path(data.get("categories") or [])

    attributes, brand = _extract_attributes(data.get("attributes") or [])
    rec["_attributes"] = attributes
    rec["brand"] = brand

    rec["_images"] = _extract_images(data.get("media_gallery_entries") or [], image_manifest)

    return rec


def iter_products(site_dir: Path) -> Iterator[dict]:
    image_manifest = load_image_manifest(site_dir)
    products_dir = site_dir / "raw" / "products"
    root = site_dir.parent.parent

    variant_to_parent: dict[str, str] = {}
    pending_standalone: list[dict] = []

    for path in sorted(products_dir.glob("*/*.json")):
        data, raw_bytes = load_json_bytes(path)
        raw_path_str = str(path.relative_to(root)).replace("\\", "/")
        crawled_at = file_crawled_at(path)

        if data.get("type_id") == "configurable":
            parent_id = str(data["id"])
            for v in data.get("variants") or []:
                vp = v.get("product") or {}
                if not vp.get("id"):
                    continue
                variant_to_parent[str(vp["id"])] = parent_id
                yield _normalize_one(
                    vp,
                    source_key=f"{path.stem}#{vp['id']}",
                    raw_path_str=raw_path_str,
                    raw_bytes=None,
                    crawled_at=crawled_at,
                    group_key=parent_id,
                    is_group_parent=False,
                    image_manifest=image_manifest,
                )
            yield _normalize_one(
                data,
                source_key=path.stem,
                raw_path_str=raw_path_str,
                raw_bytes=raw_bytes,
                crawled_at=crawled_at,
                group_key=parent_id,
                is_group_parent=True,
                image_manifest=image_manifest,
            )
        else:
            rec = _normalize_one(
                data,
                source_key=path.stem,
                raw_path_str=raw_path_str,
                raw_bytes=raw_bytes,
                crawled_at=crawled_at,
                group_key=None,
                is_group_parent=False,
                image_manifest=image_manifest,
            )
            pending_standalone.append((str(data["id"]), rec))

    for source_id, rec in pending_standalone:
        rec["group_key"] = variant_to_parent.get(source_id)
        yield rec
