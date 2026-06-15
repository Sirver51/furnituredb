"""Phase 2: complete crawl of the Rugs category (id=87, ~2,507 products).
Writes one raw product JSON per unique product id to
raw/products/<shard>/<id>.json, and queues all discovered images to aria2c.

Usage:
    uv run python crawl_rugs.py [--limit-pages N]
"""

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, product_exists, product_path, save_json

import api
import attributes

RAW_DIR = Path(__file__).parent / "raw"
CATEGORY_ID = 87
PAGE_SIZE = 200
CHUNK_SIZE = 20


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-pages", type=int, default=None)
    args = parser.parse_args()

    state = CrawlState(RAW_DIR / "crawl_state.json")

    try:
        page1 = api.fetch_listing_page(CATEGORY_ID, page=1, page_size=PAGE_SIZE)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        print(f"  [error] page 1 failed ({e!r}), aborting")
        return
    save_json(RAW_DIR / "listings" / "rugs" / "page_1.json", page1)
    total_pages = page1["page_info"]["total_pages"]
    print(f"Rugs category: total_count={page1['total_count']}, total_pages={total_pages}")

    all_ids = [item["id"] for item in page1["items"]]

    last_page = total_pages
    if args.limit_pages:
        last_page = min(total_pages, args.limit_pages)

    for page in range(2, last_page + 1):
        key = f"rugs_page_{page}"
        page_path = RAW_DIR / "listings" / "rugs" / f"page_{page}.json"
        if state.is_done(key):
            data = load_json(page_path)
        else:
            try:
                data = api.fetch_listing_page(CATEGORY_ID, page=page, page_size=PAGE_SIZE)
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                print(f"  [warning] page {page} failed ({e!r}), skipping")
                continue
            save_json(page_path, data)
            state.mark_done(key)
        all_ids += [item["id"] for item in data["items"]]

    all_ids = list(dict.fromkeys(all_ids))
    print(f"Total unique product ids: {len(all_ids)}")

    new_ids = [i for i in all_ids if not product_exists(RAW_DIR, i)]
    print(f"{len(new_ids)} not yet on disk")

    written, images_queued = 0, 0
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
        print(f"  [{min(i + CHUNK_SIZE, len(new_ids))}/{len(new_ids)}] wrote {written}, queued {images_queued} images so far")

    print(f"Done. wrote {written} new product file(s), queued {images_queued} image(s) total")


if __name__ == "__main__":
    main()
