"""Phase 1: sample up to 100 products from every leaf category slug in
raw/categories.json. Writes one raw product JSON per sampled pid to
raw/products/<shard>/<pid>.json (the full parent+variants+assets detail
record), and queues all discovered images to aria2c.

Usage:
    uv run python crawl_sample.py [--limit-categories N] [--redo SLUG ...]
"""

import argparse
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, product_exists, product_path, save_json

import api

RAW_DIR = Path(__file__).parent / "raw"
SAMPLE_SIZE = 100
CHUNK_SIZE = 25


def collect_sample_pids(slug):
    try:
        resp = api.search_category(slug, rows=100, start=0)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        print(f"  [warning] search failed ({e!r}), skipping category")
        return None, []
    save_json(RAW_DIR / "listings" / slug / "page_1.json", resp)
    num_found = resp["numFound"]
    pids = [doc["pid"] for doc in resp["docs"]]

    if num_found > 100:
        max_start = max(0, num_found - 100)
        start = random.randint(0, max_start)
        if start > 0:
            try:
                extra = api.search_category(slug, rows=100, start=start)
                save_json(RAW_DIR / "listings" / slug / f"page_start{start}.json", extra)
                pids += [doc["pid"] for doc in extra["docs"]]
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                print(f"  [warning] extra page failed ({e!r}), using page 1 only")

    pids = list(dict.fromkeys(pids))
    if len(pids) > SAMPLE_SIZE:
        pids = random.sample(pids, SAMPLE_SIZE)
    return num_found, pids


def match_pid_to_product(pid, products):
    """The detail endpoint returns one entry per distinct parent product;
    multiple requested pids (color siblings) may resolve to the same entry."""
    for product in products:
        if str(product.get("sku")) == str(pid):
            return product
        variant_skus = {str(v["sku"]) for v in product.get("variants", []) if v.get("sku")}
        if str(pid) in variant_skus:
            return product
    return None


def fetch_and_save_details(pids):
    new_pids = [p for p in pids if not product_exists(RAW_DIR, p)]
    written = 0
    images_queued = 0
    for i in range(0, len(new_pids), CHUNK_SIZE):
        chunk = new_pids[i : i + CHUNK_SIZE]
        try:
            products = api.fetch_details_batch(chunk)
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            print(f"  [warning] details batch failed ({e!r}), skipping {len(chunk)} pid(s)")
            continue
        for pid in chunk:
            product = match_pid_to_product(pid, products)
            if product is None:
                print(f"    no detail match for pid={pid}, skipping")
                continue
            save_json(product_path(RAW_DIR, pid), product)
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
        slug = cat["slug"]
        if state.is_done(slug) and slug not in args.redo:
            continue

        print(f"[{slug}]")
        num_found, pids = collect_sample_pids(slug)
        if num_found is None:
            state.mark_done(slug)
            continue
        print(f"  numFound={num_found}, sampled {len(pids)} pid(s)")
        written, images_queued = fetch_and_save_details(pids)
        print(f"  wrote {written} new product file(s), queued {images_queued} image(s)")

        state.mark_done(slug)

    print("Done.")


if __name__ == "__main__":
    main()
