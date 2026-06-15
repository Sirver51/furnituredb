"""Shared Homes R Us HTTP + image-queueing helpers, used by crawl_sample.py
and crawl_rugs.py."""

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from common.aria2 import add_download
from common.pacing import polite_delay
from common.retry import request_with_retry
from common.storage import append_jsonl

from extract import extract_product

BASE_URL = "https://www.homesrus.ae"
SITE_DIR = Path(__file__).parent
RAW_DIR = SITE_DIR / "raw"
IMAGES_DIR = SITE_DIR / "images"

AMOUNT_RE = re.compile(r"of\s+([\d,]+)\s+results")

client = httpx.Client(timeout=30, follow_redirects=True, headers={"Accept": "text/html"})


def fetch_category_page(path, page=1):
    """One paginated category listing page (24 items/page). Returns
    (items, total_count) where items is [{sku, name, url}, ...]."""
    polite_delay("homesrus")
    url = BASE_URL + path + "/"
    params = {"p": page} if page > 1 else None

    def do():
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp

    resp = request_with_retry(do, max_retries=2, base_delay=1.0)
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    for item in soup.select("li.item.product.product-item"):
        link = item.select_one("a.product-item-link")
        if not link:
            continue
        sku_el = item.select_one("[data-product-sku]")
        items.append({
            "sku": sku_el["data-product-sku"] if sku_el else None,
            "name": link.get_text(strip=True),
            "url": link["href"],
        })

    total = None
    amount_el = soup.select_one(".toolbar-amount")
    if amount_el:
        m = AMOUNT_RE.search(amount_el.get_text())
        if m:
            total = int(m.group(1).replace(",", ""))

    return items, total


def fetch_product_detail(url):
    """Full product detail page -> raw-ish record (JSON-LD + breadcrumbs +
    specs + gallery image URLs)."""
    polite_delay("homesrus")

    def do():
        resp = client.get(url)
        resp.raise_for_status()
        return resp

    resp = request_with_retry(do, max_retries=2, base_delay=1.0)
    soup = BeautifulSoup(resp.text, "html.parser")
    return extract_product(soup, url)


def queue_product_images(record):
    """Queue every gallery image to aria2c under images/<sku>/. Returns the
    number of images found (queued or already on disk)."""
    sku = record.get("sku")
    if not sku:
        return 0
    sku_dir = IMAGES_DIR / sku
    queued = 0
    for img_url in record.get("gallery") or []:
        filename = Path(urlparse(img_url).path).name
        dest = sku_dir / filename
        add_download(img_url, dir=sku_dir, out=filename, max_conns=2)
        append_jsonl(RAW_DIR / "image_manifest.jsonl", {"url": img_url, "dest": str(dest.relative_to(SITE_DIR))})
        queued += 1
    return queued
