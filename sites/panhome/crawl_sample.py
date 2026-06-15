"""Phase 1: sample up to 100 products from every leaf category in
raw/categories.json. Writes one raw product JSON per unique product id to
raw/products/<shard>/<id>.json, and queues all discovered images to aria2c.

Usage:
    uv run python crawl_sample.py [--limit-categories N] [--redo CAT_ID ...]
"""

import argparse
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, product_exists, product_path, save_json

import api
import attributes

RAW_DIR = Path(__file__).parent / "raw"
SAMPLE_SIZE = 100
CHUNK_SIZE = 20


def collect_sample_ids(category):
    cat_id = category["id"]

    try:
        page1 = api.fetch_listing_page(cat_id, page=1, page_size=200)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        print(f"  [warning] page 1 failed ({e!r}), skipping category")
        return None
    save_json(RAW_DIR / "listings" / str(cat_id) / "page_1.json", page1)
    ids = [item["id"] for item in page1["items"]]

    total_pages = page1["page_info"]["total_pages"]
    if total_pages > 1 and len(ids) > SAMPLE_SIZE:
        # already have a big enough pool from page 1
        pass
    elif total_pages > 1:
        # broaden the pool with one random additional page
        page = random.randint(2, total_pages)
        try:
            extra = api.fetch_listing_page(cat_id, page=page, page_size=100)
            save_json(RAW_DIR / "listings" / str(cat_id) / f"page_{page}.json", extra)
            ids += [item["id"] for item in extra["items"]]
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            print(f"  [warning] page {page} failed ({e!r}), using page 1 only")

    ids = list(dict.fromkeys(ids))
    if len(ids) > SAMPLE_SIZE:
        ids = random.sample(ids, SAMPLE_SIZE)
    return ids


def fetch_and_save_details(ids):
    new_ids = [i for i in ids if not product_exists(RAW_DIR, i)]
    written = 0
    images_queued = 0
    for i in range(0, len(new_ids), CHUNK_SIZE):
        chunk = new_ids[i : i + CHUNK_SIZE]
        try:
            items = api.fetch_details_batch(chunk)
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            print(f"  [warning] details batch failed ({e!r}), skipping {len(chunk)} id(s)")
            continue
        for product in items:
            attributes.strip_bloated_options(product, RAW_DIR / "attribute_dictionary.json")
            save_json(product_path(RAW_DIR, product["id"]), product)
            images_queued += api.queue_product_images(product)
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
        cat_id = str(cat["id"])
        if state.is_done(cat_id) and cat_id not in args.redo:
            continue

        print(f"[{cat['name']}] (id={cat_id}, product_count={cat['product_count']})")
        ids = collect_sample_ids(cat)
        if ids is None:
            state.mark_done(cat_id)
            continue
        print(f"  sampled {len(ids)} product id(s)")
        written, images_queued = fetch_and_save_details(ids)
        print(f"  wrote {written} new product file(s), queued {images_queued} image(s)")

        state.mark_done(cat_id)

    print("Done.")


if __name__ == "__main__":
    main()
