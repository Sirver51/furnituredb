# Home Centre (UAE) — API Notes

Site: https://www.homecentre.com/ae/en/
Platform: custom storefront (not Magento), built on:
- **Bloomreach Discovery** (`core.dxpapi.com`) for category listing / search
- Home Centre's own REST API (`www.homecentre.com/api/...`) for per-product detail
- **Amplience** CMS (`*.amplience.net`) for department navigation content

## TL;DR

- No login/cookies/session needed for either data source.
- Site sits behind Cloudflare, but plain `httpx` GETs work fine for both APIs below
  (Bloomreach is a separate third-party host entirely; the Home Centre `/api/*`
  endpoints just need one custom header — see §2).
- Two calls are enough to fully scrape a product:
  1. **Search/listing** (`core.dxpapi.com`) → gives you `pid`, title, description,
     price, gallery images, breadcrumbs, and color siblings, for many products at once.
  2. **Product detail** (`/api/catalog-browse/products/sku?productSkus=<pid>`) → gives
     you the full picture for that product *and all its color variants* in one
     response (combined `assets`, `variants`, `options`, human-readable attributes).

## 1. Search / Category Listing API (Bloomreach Discovery)

```
GET https://core.dxpapi.com/api/v1/core/
```

Query params seen on real category pages (all public — copied from captured
frontend requests, nothing user/session-specific):

| param | example | notes |
|---|---|---|
| `account_id` | `7584` | |
| `auth_key` | `uz42nl6c4906lxyv` | |
| `domain_key` | `homecentre` | |
| `request_id` | any string | frontend sends a timestamp; doesn't seem to matter |
| `view_id` | `ae` | |
| `catalog_views` | `homecentre:ae` | |
| `url` / `ref_url` | `https://www.homecentre.com/ae/en/c/household-rugsandcarpets-rugs` | category page URL |
| `request_type` | `search` | |
| `x-concept` | `homecentre` | |
| `x-env` | `prod` | |
| `x-lang` | `en` | |
| `search_type` | `category` | |
| `q` | `household-rugsandcarpets-rugs` | category slug (from `/c/<slug>` in the URL) |
| `rows` | `48` | page size; frontend default is 48 |
| `start` | `0` | 0-based offset — pagination confirmed working (`start=48` returns the next page) |
| `fl` | comma-separated field list | **must include `pid`**, otherwise 400 `"['fl must request pid']"` |

### Response shape
```json
{
  "response": {"numFound": 728, "start": 0, "docs": [ {...}, ... ]},
  "facet_counts": {...}
}
```

### Useful `fl` fields
```
pid, title, description, url, brand, price, sale_price, price_range, sale_price_range,
low_price, low_sale_price, productType, skuList, baseProductId, colorAll,
galleryImages, breadcrumbCategories, categoryFacetValue, siblingItems
```
- `description` — full marketing copy, plain string with inline `<br>`/`<b>` tags, populated.
- `galleryImages` — JSON-encoded array of `{"type":"IMAGE","url":"https://media.homecentre.com/..."}`, full-size CDN images, no auth needed.
- `breadcrumbCategories` — `["household-rugsandcarpets#Rugs & Carpets", "household-rugsandcarpets-rugs#Rugs", "household#Household"]` (`<slug>#<Label>`).
- `categoryFacetValue` — similar but with full path + image URL per level, e.g. `"03#household-rugsandcarpets-rugs#Rugs#false#https://media.homecentre.com/i/homecentre/household-rugsandcarpets-rugs"`.
- `productType` — `"SIMPLE"` or `"VARIANT_BASED"` (has color/size variants).
- `price` / `sale_price` / `low_price` — for `VARIANT_BASED` products these reflect the *specific sku* returned as `pid`, not necessarily the cheapest variant.

### ⚠️ `siblingItems` gotcha

For multi-color products, `siblingItems` comes back as a list of **single-character
strings** that together spell out one JSON string (a Solr/Bloomreach
multi-valued-field artifact — the JSON array got exploded into individual
characters). To use it:

```python
sib = doc.get("siblingItems", [])
siblings = json.loads("".join(sib)) if sib else []
# -> [{"code": "164398428", "colorCode": ["Beige", "بيج"],
#      "thumbnailImg": "https://media.homecentre.com/i/homecentre/164398428-....jpg"}]
```

`code` is the sibling's own `pid`/sku — fetch its detail the same way as the main
product, or just rely on the detail call below (§2), which already returns every
color variant in one shot. Single-color products simply omit `siblingItems` entirely.

## 2. Product Detail API (Home Centre native)

```
GET https://www.homecentre.com/api/catalog-browse/products/sku?productSkus=<sku>
Header: x-context-request: {"applicationId":"hc-ae","tenantId":"5DF1363059675161A85F576D"}
```

- **The header is the only thing required** — no cookies, no session. Without it,
  the endpoint returns `{"products": [], ...}` even for a valid sku.
- `productSkus` = the `pid` (or any sibling's sku) from search. One call returns the
  **parent product plus every color variant**, including combined images.
- Response: `{"products": [...], "productIdsForMissingEntities": [...], "productUrisForMissingEntities": [...]}`

### `products[0]` fields of interest

| field | notes |
|---|---|
| `description` | populated, plain string w/ `<b>`/`</br>` tags |
| `metaDescription` | populated SEO description |
| `breadcrumbs` | `[{"label": "Household", "uri": "/household"}, ..., {"label": "<product name>"}]` |
| `options` | e.g. Color: `{"type":"VARIANT_DISTINGUISHING","attributeChoice":{"attributeName":"Color","type":"COLOR","allowedValues":[{"id","label","value":"<sibling sku>","displayOrder"}]}}` |
| `variants` | one entry per color/size sku, each with its own `priceInfo`/`defaultPrice`/`salePrice` |
| `assets` | **all** images for **all** color variants in one list: `{"type":"IMAGE","url":"https://media.homecentre.com/...","tags":["color:<sku>"]}` — filter by `tags` to get per-color galleries |
| `primaryAsset` | hero image (same shape as one `assets` entry) |
| `productAttributeDetails` | grouped, human-readable: `[{"groupName","groupDisplayName","style","attributeDetails":{"<code>":{"value","nameLabel"}}}]` |
| `attributes` | flattened `[{"nameLabel","value"}]` — same data, ungrouped |
| `breadcrumbs`/`categoryIdsWithParents`/`parentCategories` | category info |

**No code→label resolution needed** — unlike Panhome, `productAttributeDetails` /
`attributes` values are already human-readable strings (e.g. `primaryMaterial:
"Polyester"`, `shape: "Rectangle"`, `pileHeight: "High"`).

A second endpoint, `/api/product-data/productdata` (same header), also returns
product data — not yet compared in detail against `catalog-browse/products/sku`,
but the latter alone appears sufficient for scraping.

## 3. Category / department discovery

```
GET https://homecentrelive.cdn.content.amplience.net/content/key/homecentreae-DepartmentListing?depth=all&format=inlined&locale=en
```
- Amplience CMS, public, no auth.
- Returns only the **top-level department list** (`All`, `Furniture`, `Household`,
  `Kids`, `Baby`, `New Arrivals`) with URLs like `/department/household` — not a
  full category tree.
- Sub-category slugs (e.g. `household-rugsandcarpets-rugs` for Rugs) come from the
  category page URL path (`/c/<slug>`) and/or from `categoryFacetValue` /
  `breadcrumbCategories` in search results. No single endpoint found yet that
  returns a full crawlable category tree with slugs + product counts (unlike
  Panhome's `categories` GraphQL query) — if needed, derive it by walking
  `categoryFacetValue` across a broad search, or explore Amplience further.

## Images

CDN: `https://media.homecentre.com/i/homecentre/<...>.jpg?v=N` — public, no auth,
no special headers. Same URLs appear in both `galleryImages` (search) and `assets`
(detail).

## Open questions / not yet tested

- `/api/product-data/productdata` — overlap with `catalog-browse/products/sku` not
  compared.
- Rate limiting on either API at scale.
- Longevity of the Bloomreach `account_id`/`auth_key`/`domain_key` (embedded in
  frontend JS, typically long-lived but could rotate on a redeploy).
- Max `rows` per page for the search API (48 is the frontend default; not pushed
  higher).
- Full category tree / slug list beyond the few categories seen in captures.

## Tooling in this repo

- `capture_network.py <url> <label> [--filter SUBSTRING] --outdir sites/homecentre/captures`
  — interactive capture.
- `explore.py <url> <label> [--scroll N] [--filter SUBSTRING] --outdir sites/homecentre/captures`
  — headless capture + screenshot.
- `analyze_capture.py sites/homecentre/captures/<label>.json [--full INDEX]` — summarize
  captured requests.
