"""Pure HTML/JSON-LD extraction helpers for Homes R Us product detail pages.
No I/O - takes a BeautifulSoup of a product page and returns a raw-ish dict."""

import json
from html import unescape


def extract_jsonld(soup, type_):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        if data.get("@type") == type_:
            return data
    return None


def extract_breadcrumbs(soup):
    breadcrumb_ld = extract_jsonld(soup, "BreadcrumbList")
    if not breadcrumb_ld:
        return []
    return [
        {"name": unescape(item["name"]), "url": item.get("item")}
        for item in breadcrumb_ld.get("itemListElement", [])
    ]


def extract_specs(soup):
    specs = {}
    for li in soup.select("ul.product-attribute-list li"):
        spans = li.find_all("span")
        if len(spans) >= 2:
            specs[spans[0].get_text(strip=True).rstrip(":")] = spans[1].get_text(strip=True)
    return specs


def extract_gallery(soup):
    for script in soup.find_all("script", type="text/x-magento-init"):
        text = script.string or ""
        if "mage/gallery/gallery" not in text:
            continue
        data = json.loads(text)
        gallery = data["[data-gallery-role=gallery-placeholder]"]["mage/gallery/gallery"]["data"]
        return [unescape(g["img"]) for g in gallery if g.get("type") == "image"]
    return []


def extract_product(soup, url):
    """Full raw-ish product record: JSON-LD Product (price/offers/rating kept
    as-is) + breadcrumbs + specs + gallery image URLs."""
    product_ld = extract_jsonld(soup, "Product") or {}
    return {
        "url": url,
        "sku": product_ld.get("sku"),
        "name": product_ld.get("name"),
        "description": unescape(product_ld.get("description", "")),
        "image": unescape(product_ld["image"]) if product_ld.get("image") else None,
        "brand": product_ld.get("brand"),
        "offers": product_ld.get("offers"),
        "aggregateRating": product_ld.get("aggregateRating"),
        "breadcrumbs": extract_breadcrumbs(soup),
        "specs": extract_specs(soup),
        "gallery": extract_gallery(soup),
    }
