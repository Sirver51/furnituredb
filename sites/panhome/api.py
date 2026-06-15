"""Shared Panhome GraphQL + image-queueing helpers, used by crawl_sample.py
and crawl_rugs.py."""

import json
from pathlib import Path
from urllib.parse import urlencode

import httpx

from common.aria2 import add_download
from common.pacing import polite_delay
from common.retry import request_with_retry
from common.storage import append_jsonl

ENDPOINT = "https://www.panhomestores.com/uae_en/graphql"
SITE_DIR = Path(__file__).parent
RAW_DIR = SITE_DIR / "raw"
IMAGES_DIR = SITE_DIR / "images"

client = httpx.Client(headers={"Accept": "application/json"}, timeout=30)


def hash_get(hash_, **params):
    encoded = {}
    for k, v in params.items():
        encoded[k] = json.dumps(v) if not isinstance(v, str) else v
    encoded["hash"] = hash_
    encoded["_currency"] = ""
    url = ENDPOINT + "?" + urlencode(encoded)
    polite_delay("panhome")

    def do():
        resp = client.get(url)
        return _unwrap(resp)

    return request_with_retry(do)


def post_query(query, variables=None):
    polite_delay("panhome")

    def do():
        resp = client.post(ENDPOINT, json={"query": query, "variables": variables or {}})
        return _unwrap(resp)

    return request_with_retry(do)


def _unwrap(resp):
    """Return the GraphQL `data` payload, even on a non-2xx status: this
    server returns HTTP 404 for responses that carry partial `errors`
    alongside otherwise-complete `data` (e.g. a single resolver failure on
    one variant's media_gallery_entries). Only raise if `data` is absent."""
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise
    if body.get("data") is not None:
        if body.get("errors"):
            print(f"  [warning] partial GraphQL errors: {body['errors']}")
        return body["data"]
    resp.raise_for_status()
    raise RuntimeError(body.get("errors", body))


def fetch_listing_page(category_id, page, page_size):
    """One page of category product listing. Returns the raw `products` object
    (total_count, page_info, items[])."""
    return hash_get(
        "262598812",
        sort_1={"position": "ASC"},
        filter_1={"price": {}, "category_id": {"eq": category_id}, "customer_group_id": {"eq": "0"}},
        pageSize_1=str(page_size),
        currentPage_1=str(page),
    )["products"]


def fetch_details_batch(ids):
    """Full product detail (variants, attributes, price_range, description)
    for up to 20 ids in one call - the response caps at 20 items regardless
    of pageSize_1, so callers should chunk ids into groups of <=20."""
    data = hash_get(
        "1455383406",
        filter_1={"id": {"in": [str(i) for i in ids]}, "customer_group_id": {"eq": "0"}},
        pageSize_1="20",
        currentPage_1="1",
    )
    return data["products"]["items"]


def queue_product_images(product):
    """Queue every media gallery image (parent + every variant) to aria2c.
    Returns the number of images found (queued or already on disk)."""
    queued = 0
    for media in product.get("media_gallery_entries") or []:
        _queue_image(media, product["sku"])
        queued += 1
    for v in product.get("variants", []):
        vp = v["product"]
        for media in vp.get("media_gallery_entries") or []:
            _queue_image(media, vp["sku"])
            queued += 1
    return queued


def _queue_image(media, sku):
    url = media["base"]["url"]
    filename = Path(media["file"]).name
    sku_dir = IMAGES_DIR / sku
    dest = sku_dir / filename
    add_download(url, dir=sku_dir, out=filename, max_conns=8)
    append_jsonl(RAW_DIR / "image_manifest.jsonl", {"url": url, "dest": str(dest.relative_to(SITE_DIR))})
