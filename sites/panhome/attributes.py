"""Attribute bloat handling shared by crawl_sample.py / crawl_rugs.py.

Multiselect attributes (notably `features`, ~4,946 options; `size`, ~575
options) ship their ENTIRE catalog-wide option list on every product
response. To avoid massive duplication on disk, any `attribute_options` array
longer than OPTION_BLOAT_THRESHOLD is stripped out of the per-product JSON and
merged into a shared raw/attribute_dictionary.json[attribute_code] dict
instead. This is the only non-raw transformation in the pipeline, and it's
lossless: nothing is dropped that isn't reconstructable from the dictionary.

(Tier 2 - codes like `color`/`material`/`shape` that never carry
attribute_options at all - is handled separately by build_attribute_dictionary.py.)
"""

import threading

from common.storage import load_json, save_json

OPTION_BLOAT_THRESHOLD = 50

_lock = threading.Lock()


def strip_bloated_options(product, dict_path):
    """Mutates `product` in place. For every attribute on the parent and on
    each variant's nested product, if `attribute_options` has more than
    OPTION_BLOAT_THRESHOLD entries, remove it and merge {value: option} into
    raw/attribute_dictionary.json[attribute_code]."""
    new_entries = {}

    def process(attrs):
        for a in attrs or []:
            opts = a.get("attribute_options")
            if opts and len(opts) > OPTION_BLOAT_THRESHOLD:
                code = a["attribute_code"]
                new_entries.setdefault(code, {})
                for o in opts:
                    new_entries[code][str(o["value"])] = o
                del a["attribute_options"]

    process(product.get("attributes"))
    for v in product.get("variants", []):
        process(v.get("product", {}).get("attributes"))

    if new_entries:
        _merge_dictionary(dict_path, new_entries)


def _merge_dictionary(dict_path, new_entries):
    with _lock:
        existing = load_json(dict_path, {})
        for code, options in new_entries.items():
            existing.setdefault(code, {})
            existing[code].update(options)
        save_json(dict_path, existing)
