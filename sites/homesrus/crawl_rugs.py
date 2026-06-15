"""Phase 2: complete crawl of the Rugs & Carpets category
(path=/en/household/decor-and-furnishings/floor-coverings/rugs-carpets,
total~178, 24/page). Writes one raw product JSON per sku to
raw/products/<shard>/<sku>.json, and queues all discovered images to aria2c.

Usage:
    uv run python crawl_rugs.py [--limit-pages N]
"""

import argparse
import math
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, save_json

import api
from crawl_sample import fetch_and_save_details

RAW_DIR = Path(__file__).parent / "raw"
PATH = "/en/household/decor-and-furnishings/floor-coverings/rugs-carpets"
PAGE_SIZE = 24


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-pages", type=int, default=None)
    args = parser.parse_args()

    state = CrawlState(RAW_DIR / "crawl_state.json")

    try:
        items, total = api.fetch_category_page(PATH, page=1)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        print(f"  [error] page 1 failed ({e!r}), aborting")
        return
    save_json(RAW_DIR / "listings" / "rugs" / "page_1.json", {"items": items, "total": total})
    print(f"Rugs category: total={total}")

    total_pages = math.ceil(total / PAGE_SIZE)
    pages = list(range(2, total_pages + 1))
    if args.limit_pages:
        pages = pages[: max(0, args.limit_pages - 1)]

    all_items = list(items)
    for page in pages:
        key = f"rugs_page_{page}"
        page_path = RAW_DIR / "listings" / "rugs" / f"page_{page}.json"
        if state.is_done(key):
            page_items = load_json(page_path)["items"]
        else:
            try:
                page_items, _ = api.fetch_category_page(PATH, page=page)
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                print(f"  [warning] page {page} failed ({e!r}), skipping")
                continue
            save_json(page_path, {"items": page_items})
            state.mark_done(key)
        all_items += page_items

    seen = set()
    deduped = []
    for it in all_items:
        if it["sku"] and it["sku"] not in seen:
            seen.add(it["sku"])
            deduped.append(it)
    print(f"Total unique products: {len(deduped)}")

    written, images_queued = fetch_and_save_details(deduped)
    print(f"Done. wrote {written} new product file(s), queued {images_queued} image(s) total")


if __name__ == "__main__":
    main()
