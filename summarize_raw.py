"""Print per-site progress/sanity stats: categories done, products written,
images on disk, and disk usage of raw/ and images/.

Usage:
    uv run python summarize_raw.py [site ...]   # default: all sites
"""

import json
import sys
from pathlib import Path

SITES = ["panhome", "homecentre", "homesrus"]
ROOT = Path(__file__).parent


def _count_and_size(dir_path: Path):
    count = 0
    size = 0
    if not dir_path.exists():
        return 0, 0
    for p in dir_path.rglob("*"):
        if p.is_file():
            count += 1
            size += p.stat().st_size
    return count, size


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def summarize(site: str):
    site_dir = ROOT / "sites" / site
    raw_dir = site_dir / "raw"
    images_dir = site_dir / "images"

    categories = json.loads((raw_dir / "categories.json").read_text(encoding="utf-8")) \
        if (raw_dir / "categories.json").exists() else []
    state = json.loads((raw_dir / "crawl_state.json").read_text(encoding="utf-8")) \
        if (raw_dir / "crawl_state.json").exists() else {"categories_done": []}

    products_count, products_size = _count_and_size(raw_dir / "products")
    images_count, images_size = _count_and_size(images_dir)
    raw_count, raw_size = _count_and_size(raw_dir)

    print(f"== {site} ==")
    print(f"  categories: {len(state.get('categories_done', []))}/{len(categories)} done")
    print(f"  products:   {products_count} files ({_fmt_size(products_size)})")
    print(f"  images:     {images_count} files ({_fmt_size(images_size)})")
    print(f"  raw/ total: {_fmt_size(raw_size)}")
    print()


def main():
    sites = sys.argv[1:] or SITES
    for site in sites:
        summarize(site)


if __name__ == "__main__":
    main()
