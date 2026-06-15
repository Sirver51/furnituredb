"""Phase 2: complete crawl of the Rugs category
(slug=household-rugsandcarpets-rugs, numFound~728). Writes one raw product
JSON per unique pid to raw/products/<shard>/<pid>.json, and queues all
discovered images to aria2c.

Usage:
    uv run python crawl_rugs.py [--limit-pages N]
"""

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import CrawlState, load_json, save_json

import api
from crawl_sample import fetch_and_save_details

RAW_DIR = Path(__file__).parent / "raw"
SLUG = "household-rugsandcarpets-rugs"
PAGE_SIZE = 200


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-pages", type=int, default=None)
    args = parser.parse_args()

    state = CrawlState(RAW_DIR / "crawl_state.json")

    resp = api.search_category(SLUG, rows=PAGE_SIZE, start=0)
    save_json(RAW_DIR / "listings" / "rugs" / "start_0.json", resp)
    num_found = resp["numFound"]
    print(f"Rugs category: numFound={num_found}")

    all_pids = [doc["pid"] for doc in resp["docs"]]

    starts = list(range(PAGE_SIZE, num_found, PAGE_SIZE))
    if args.limit_pages:
        starts = starts[: max(0, args.limit_pages - 1)]

    for start in starts:
        key = f"rugs_start_{start}"
        page_path = RAW_DIR / "listings" / "rugs" / f"start_{start}.json"
        if state.is_done(key):
            data = load_json(page_path)
        else:
            try:
                data = api.search_category(SLUG, rows=PAGE_SIZE, start=start)
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                print(f"  [warning] page start={start} failed ({e!r}), skipping")
                continue
            save_json(page_path, data)
            state.mark_done(key)
        all_pids += [doc["pid"] for doc in data["docs"]]

    all_pids = list(dict.fromkeys(all_pids))
    print(f"Total unique pids: {len(all_pids)}")

    written, images_queued = fetch_and_save_details(all_pids)
    print(f"Done. wrote {written} new product file(s), queued {images_queued} image(s) total")


if __name__ == "__main__":
    main()
