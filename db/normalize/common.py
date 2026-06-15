"""Shared helpers for per-site normalizers."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

WHITESPACE_RE = re.compile(r"\s+")


def clean_html(html: str | None) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def file_crawled_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def load_json_bytes(path: Path) -> tuple[dict, bytes]:
    raw_bytes = path.read_bytes()
    return json.loads(raw_bytes.decode("utf-8")), raw_bytes


def load_image_manifest(site_dir: Path) -> dict[str, str]:
    """Map image URL -> local path (forward-slash, relative to site_dir)."""
    manifest_path = site_dir / "raw" / "image_manifest.jsonl"
    mapping: dict[str, str] = {}
    if not manifest_path.exists():
        return mapping
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            mapping[entry["url"]] = entry["dest"].replace("\\", "/")
    return mapping


def base_product() -> dict:
    """Default product dict with all columns set to None, plus empty sub-lists."""
    return {
        "source_id": None,
        "group_key": None,
        "is_group_parent": 0,
        "sku": None,
        "name": None,
        "description": None,
        "brand": None,
        "url": None,
        "currency": "AED",
        "price": None,
        "regular_price": None,
        "discount_pct": None,
        "availability": None,
        "rating_value": None,
        "rating_count": None,
        "taxonomy_path": None,
        "_images": [],
        "_attributes": [],
    }
