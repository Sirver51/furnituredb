"""Phase 1: sample up to 100 products from every leaf category path in
raw/categories.json. Writes one raw product JSON per sku to
raw/products/<shard>/<sku>.json, and queues all discovered images to aria2c.

Usage:
    uv run python crawl_sample.py [--limit-categories N] [--redo PATH ...]
"""

import argparse
import math
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, product_exists, product_path, save_json

import api

RAW_DIR = Path(__file__).parent / "raw"
SAMPLE_SIZE = 100
PAGE_SIZE = 24


def _listing_dir(path):
    return RAW_DIR / "listings" / path.strip("/").replace("/", "_")


def collect_sample_items(path):
    try:
        items, total = api.fetch_category_page(path, page=1)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        print(f"  [warning] page 1 failed ({e!r}), skipping category")
        return None, []
    save_json(_listing_dir(path) / "page_1.json", {"items": items, "total": total})

    if total and total > PAGE_SIZE:
        total_pages = math.ceil(total / PAGE_SIZE)
        if total_pages > 1 and len(items) < SAMPLE_SIZE:
            page = random.randint(2, total_pages)
            try:
                extra, _ = api.fetch_category_page(path, page=page)
                save_json(_listing_dir(path) / f"page_{page}.json", {"items": extra})
                items = items + extra
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                print(f"  [warning] page {page} failed ({e!r}), using page 1 only")

    seen = set()
    deduped = []
    for it in items:
        if it["sku"] and it["sku"] not in seen:
            seen.add(it["sku"])
            deduped.append(it)

    if len(deduped) > SAMPLE_SIZE:
        deduped = random.sample(deduped, SAMPLE_SIZE)
    return total, deduped


def fetch_and_save_details(items):
    new_items = [it for it in items if it["sku"] and not product_exists(RAW_DIR, it["sku"])]
    written = 0
    images_queued = 0
    for it in new_items:
        try:
            record = api.fetch_product_detail(it["url"])
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            print(f"    [warning] detail fetch failed ({e!r}) for {it['url']}, skipping")
            continue
        if not record.get("sku"):
            print(f"    no sku in detail for {it['url']}, skipping")
            continue
        save_json(product_path(RAW_DIR, record["sku"]), record)
        images_queued += api.queue_product_images(record)
        written += 1
    return written, images_queued


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-categories", type=int, default=None)
    parser.add_argument("--redo", action="append", default=[])
    args = parser.parse_args()

    categories = load_json(RAW_DIR / "categories.json")
    if args.limit_categories:
        categories = categories[: args.limit_categories]

    state = CrawlState(RAW_DIR / "crawl_state.json")

    for cat in categories:
        path = cat["path"]
        if state.is_done(path) and path not in args.redo:
            continue

        print(f"[{path}]")
        total, items = collect_sample_items(path)
        if total is None and not items:
            state.mark_done(path)
            continue
        print(f"  total={total}, sampled {len(items)} item(s)")
        written, images_queued = fetch_and_save_details(items)
        print(f"  wrote {written} new product file(s), queued {images_queued} image(s)")

        state.mark_done(path)

    print("Done.")


if __name__ == "__main__":
    main()
