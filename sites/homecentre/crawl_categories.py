"""Build raw/categories.json: every "leaf" category slug from Home Centre's
category sitemap (https://www.homecentre.com/ae/en/sitemap-category_1.xml).

A slug is treated as a leaf if no other slug in the sitemap starts with
"<slug>-" (i.e. nothing subdivides it further) - hyphens in these slugs are
hierarchy separators (e.g. "babyandkids-bathandstorage-bath-bathmats").

Usage:
    uv run python crawl_categories.py
"""

import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import save_json

SITEMAP_URL = "https://www.homecentre.com/ae/en/sitemap-category_1.xml"
RAW_DIR = Path(__file__).parent / "raw"


def main():
    resp = httpx.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()
    locs = re.findall(r"<loc>(.*?)</loc>", resp.text)
    slugs = [l.rsplit("/c/", 1)[1] for l in locs if "/c/" in l]
    slug_set = set(slugs)

    leaves = sorted(s for s in slug_set if not any(o.startswith(s + "-") for o in slug_set if o != s))

    save_json(RAW_DIR / "categories.json", [{"slug": s} for s in leaves])
    save_json(RAW_DIR / "all_category_slugs.json", sorted(slug_set))

    print(f"Found {len(slug_set)} total category slugs, {len(leaves)} leaf-like")
    print(f"Wrote {RAW_DIR / 'categories.json'}")


if __name__ == "__main__":
    main()
