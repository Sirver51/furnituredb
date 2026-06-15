"""Build raw/categories.json: every "leaf" category path under the
household/ and furniture/ trees, found in Homes R Us's sitemap
(https://www.homesrus.ae/en/media/hru/sitemap-1-{1,2}.xml).

The sitemap also lists ~9,100 individual product pages (matched and
discarded here) plus many single-segment promotional/collection rollups
(hru-all-products, *-collection, last-chance, online-exclusives, etc.) that
mirror the same products under household/furniture - those are excluded, same
rationale as Panhome's Sale/Online Exclusive/Discount exclusion.

A path is a "leaf" if no other candidate path starts with "<path>/" (i.e.
nothing subdivides it further).

Usage:
    uv run python crawl_categories.py
"""

import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import save_json

SITEMAP_URLS = [f"https://www.homesrus.ae/en/media/hru/sitemap-1-{n}.xml" for n in (1, 2)]
RAW_DIR = Path(__file__).parent / "raw"

PRODUCT_RE = re.compile(r"^https://www\.homesrus\.ae/en/(\d{13})-[^/]+/?$")
CATEGORY_RE = re.compile(r"^https://www\.homesrus\.ae(/en/[a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)+)/?$")
ALLOWED_ROOTS = {"household", "furniture"}


def main():
    all_locs = []
    for url in SITEMAP_URLS:
        resp = httpx.get(url, timeout=60)
        resp.raise_for_status()
        all_locs += re.findall(r"<loc>(.*?)</loc>", resp.text)
    all_locs = list(dict.fromkeys(all_locs))

    paths = set()
    for loc in all_locs:
        if PRODUCT_RE.match(loc):
            continue
        m = CATEGORY_RE.match(loc)
        if m and m.group(1).split("/")[2] in ALLOWED_ROOTS:
            paths.add(m.group(1))

    leaves = sorted(p for p in paths if not any(o.startswith(p + "/") for o in paths if o != p))

    save_json(RAW_DIR / "categories.json", [{"path": p} for p in leaves])
    save_json(RAW_DIR / "all_category_paths.json", sorted(paths))

    print(f"Found {len(all_locs)} sitemap urls, {len(paths)} category path(s) under {sorted(ALLOWED_ROOTS)}, {len(leaves)} leaf-like")
    print(f"Wrote {RAW_DIR / 'categories.json'}")


if __name__ == "__main__":
    main()
