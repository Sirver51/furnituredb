"""Shared Home Centre API helpers (Bloomreach search + native product detail
+ image queueing), used by crawl_sample.py and crawl_rugs.py."""

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from common.aria2 import add_download
from common.pacing import polite_delay
from common.retry import request_with_retry
from common.storage import append_jsonl

SEARCH_URL = "https://core.dxpapi.com/api/v1/core/"
DETAIL_URL = "https://www.homecentre.com/api/catalog-browse/products/sku"

SITE_DIR = Path(__file__).parent
RAW_DIR = SITE_DIR / "raw"
IMAGES_DIR = SITE_DIR / "images"

DETAIL_HEADERS = {
    "x-context-request": json.dumps({"applicationId": "hc-ae", "tenantId": "5DF1363059675161A85F576D"}),
    "Accept": "application/json",
}

FL_FIELDS = (
    "pid,title,description,url,brand,price,sale_price,price_range,sale_price_range,"
    "low_price,low_sale_price,productType,skuList,baseProductId,colorAll,"
    "galleryImages,breadcrumbCategories,categoryFacetValue,siblingItems"
)

client = httpx.Client(headers={"Accept": "application/json"}, timeout=30)


def search_category(slug, rows, start=0):
    """One Bloomreach Discovery search page for category `slug`. Returns the
    raw `response` object (numFound, start, docs[])."""
    params = {
        "account_id": "7584",
        "auth_key": "uz42nl6c4906lxyv",
        "domain_key": "homecentre",
        "request_id": "1",
        "view_id": "ae",
        "catalog_views": "homecentre:ae",
        "url": f"https://www.homecentre.com/ae/en/c/{slug}",
        "ref_url": f"https://www.homecentre.com/ae/en/c/{slug}",
        "request_type": "search",
        "x-concept": "homecentre",
        "x-env": "prod",
        "x-lang": "en",
        "search_type": "category",
        "q": slug,
        "rows": str(rows),
        "start": str(start),
        "fl": FL_FIELDS,
    }
    polite_delay("homecentre")

    def do():
        resp = client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        return resp.json()["response"]

    return request_with_retry(do)


def fetch_details_batch(skus):
    """skus: list of pid/sku strings. Returns the `products` list - each
    entry is a parent product combined with all of its color variants."""
    polite_delay("homecentre")

    def do():
        resp = client.get(DETAIL_URL, params={"productSkus": ",".join(str(s) for s in skus)}, headers=DETAIL_HEADERS)
        resp.raise_for_status()
        return resp.json()["products"]

    return request_with_retry(do)


def queue_product_images(product):
    """Queue every asset image to aria2c, grouped under images/<sku>/ by the
    asset's color:<sku> tag (falling back to the parent sku). Returns the
    number of images found (queued or already on disk)."""
    queued = 0
    for asset in product.get("assets") or []:
        if asset.get("type") != "IMAGE":
            continue
        url = asset.get("url") or ""
        if not url.startswith("http"):
            # Some "shadeColor:" swatch assets carry a bare filename
            # (e.g. "163666469-.jpg") instead of a full CDN URL - unusable.
            continue
        tags = asset.get("tags") or []
        color_tag = next((t.split(":", 1)[1] for t in tags if t.startswith("color:")), None)
        sku_dir = IMAGES_DIR / (color_tag or product["sku"])
        filename = Path(urlparse(url).path).name
        dest = sku_dir / filename
        add_download(url, dir=sku_dir, out=filename, max_conns=8)
        append_jsonl(RAW_DIR / "image_manifest.jsonl", {"url": url, "dest": str(dest.relative_to(SITE_DIR))})
        queued += 1
    return queued
