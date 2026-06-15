"""Tier-2 attribute dictionary post-pass.

attributes.py (tier 1) strips and dictionary-ifies any `attribute_options`
array with >50 entries as products are crawled. But some select/multiselect
codes (notably `color`, `material`, `shape`) never carry `attribute_options`
at all anywhere in the per-product responses - this script scans every file
under raw/products/, finds attribute codes used that still have no entry in
raw/attribute_dictionary.json, and resolves them in one global
`customAttributeMetadata` query.

Run after crawl_sample.py / crawl_rugs.py (safe to re-run any time - only
fetches codes not already present).

Usage:
    uv run python build_attribute_dictionary.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.storage import load_json, save_json

import api

RAW_DIR = Path(__file__).parent / "raw"
DICT_PATH = RAW_DIR / "attribute_dictionary.json"

CODED_TYPES = {"select", "multiselect"}


def fetch_attribute_dictionary(codes):
    codes = sorted(c for c in codes if re.fullmatch(r"[a-zA-Z0-9_]+", c))
    if not codes:
        return {}
    attrs_literal = ", ".join(f'{{attribute_code: "{c}", entity_type: "4"}}' for c in codes)
    query = f"""
    {{
      customAttributeMetadata(attributes: [{attrs_literal}]) {{
        items {{
          attribute_code
          attribute_options {{ value label }}
        }}
      }}
    }}
    """
    data = api.post_query(query)
    result = {}
    for item in data["customAttributeMetadata"]["items"]:
        opts = item.get("attribute_options") or []
        result[item["attribute_code"]] = {str(o["value"]): {"value": o["value"], "label": o["label"]} for o in opts}
    return result


def find_missing_codes(attrs, known_codes, needed):
    for a in attrs or []:
        if a["attribute_type"] not in CODED_TYPES:
            continue
        if not a.get("attribute_value"):
            continue
        if a.get("attribute_options"):
            continue
        if a["attribute_code"] in known_codes:
            continue
        needed.add(a["attribute_code"])


def main():
    existing = load_json(DICT_PATH, {})
    needed = set()

    product_files = list((RAW_DIR / "products").glob("*/*.json"))
    print(f"Scanning {len(product_files)} product file(s)...")
    for f in product_files:
        product = load_json(f)
        find_missing_codes(product.get("attributes"), existing, needed)
        for v in product.get("variants", []):
            find_missing_codes(v.get("product", {}).get("attributes"), existing, needed)

    needed -= set(existing.keys())
    print(f"Need dictionaries for {len(needed)} code(s): {sorted(needed)}")
    if needed:
        fetched = fetch_attribute_dictionary(needed)
        existing.update(fetched)
        save_json(DICT_PATH, existing)
        print(f"Updated {DICT_PATH}")
    else:
        print("Nothing to do.")


if __name__ == "__main__":
    main()
