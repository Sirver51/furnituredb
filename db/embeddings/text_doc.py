"""Curated text document for product-level (`vec_text`) embeddings.

v1 heuristic: `attribute.name_canonical` isn't populated yet (cross-site
vocabulary work is deferred, see docs/db_strategy.md open items), so specs are
selected by matching `name_raw.lower()` against this allowlist instead. Covers
material/color/shape/style/dimensions/capacity/features across all three
sites. Excludes SKU/URL/IDs/price/availability/ratings/warranty boilerplate --
those stay in `product_fts.specs` for lexical search only.
"""

SPEC_ALLOWLIST = {
    "color", "colour",
    "material", "primarymaterial", "secondarymaterial", "sec material",
    "legmaterial", "upholstery", "filling", "sofa filling",
    "shape", "style", "pattern", "type", "theme", "tabletop",
    "size", "mattress size", "widthcm", "heightcm", "lengthcm", "depthcm",
    "item length", "item width/depth", "item height",
    "standard unit size", "standardunitsize", "diameter",
    "seating capacity", "capacity", "number of drawers",
    "features", "set includes / unit components", "setincludes", "collectionname",
    "mattress type", "mattress firmness", "mattress thickness (cm)",
}


def build_text_doc(product: dict, attributes: list[dict]) -> str:
    """`product`: row dict with name/description/brand/taxonomy_path.
    `attributes`: row dicts with name_raw/value_raw for that product."""
    parts = [product["name"]]

    if product.get("description"):
        parts.append(product["description"])

    if product.get("brand"):
        parts.append(f"Brand: {product['brand']}")

    if product.get("taxonomy_path"):
        parts.append("Category: " + product["taxonomy_path"].replace("/", " > "))

    specs = [
        f"{a['name_raw']}: {a['value_raw']}"
        for a in attributes
        if a["name_raw"].strip().lower() in SPEC_ALLOWLIST
    ]
    if specs:
        parts.append("Specs: " + "; ".join(specs))

    return "\n".join(parts)
