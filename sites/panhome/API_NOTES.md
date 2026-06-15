# Panhome Stores (UAE) — GraphQL API Notes

Site: https://www.panhomestores.com/uae_en/
Platform: Magento 2 + custom modules (Pan Emirates / Pan Home storefront)
Endpoint: `POST/GET https://www.panhomestores.com/uae_en/graphql`

## TL;DR

- No authentication, no cookies, no session needed for catalog browsing.
- Cloudflare sits in front of the site, but plain `httpx` requests to `/uae_en/graphql`
  are **not** blocked (verified with no cookies / no special TLS handling).
- Two ways to query:
  1. **Standard POST GraphQL** with your own `query` text — works, but the
     "rich" product type (with custom `attributes`, `configurable_options`,
     `variants`, etc.) is **not reachable** this way (see below).
  2. **"Persisted query" GET requests** (`?hash=<number>&...`) — these are
     fixed queries baked into the storefront's frontend build. The numeric
     `hash` is a custom cache key; the origin resolves it **without needing
     the query text**, and works for arbitrary variable values (confirmed on
     cache MISS too). This is how to get the full rich product data.
- Introspection is disabled (`{ __schema { ... } }` → 500 Internal server error).

## Standard POST GraphQL (your own query text)

```
POST https://www.panhomestores.com/uae_en/graphql
Content-Type: application/json
{"query": "..."}
```

### Category tree
```graphql
{
  categories(filters: {parent_id: {eq: "2"}}, pageSize: 100) {
    total_count
    items {
      id uid name url_path url_key level
      children_count product_count include_in_menu is_anchor
    }
  }
}
```
- Root category id = `2` ("Default Category", 31 children).
- Always query by `parent_id` filter to walk down the tree.
- **Gotcha:** requesting the `children` field directly on `categories.items`
  errors with `"Internal server error"` — don't use it, query each level via
  `parent_id` instead.
- **Gotcha:** `parent_id` can be used as a *filter* but cannot be requested
  as an *output field* on `CategoryTree` ("Cannot query field parent_id").

### Basic full-text search (limited fields, no `attributes`)
```graphql
{
  products(search: "rug", pageSize: 5, currentPage: 1) {
    total_count
    items { id sku name url_key __typename }
  }
}
```
Works for plain search but `ProductInterface`/`SimpleProduct`/`BundleProduct`/
`ConfigurableProduct` do **not** expose the custom `attributes` field via this
path — attempting `... on SimpleProduct { attributes { ... } }` errors with
`"Cannot query field attributes on type SimpleProduct"`.

### Stock by SKU
```graphql
query($skus_1:[String]) {
  getAvailableProductQty(skus: $skus_1) { sku available_qty }
}
```

## Persisted-query GET endpoints (rich product data)

General shape:
```
GET https://www.panhomestores.com/uae_en/graphql?hash=<N>&<vars as JSON-encoded query params>&_currency=""
```

### 1. Category product listing (paginated) — `hash=262598812`
```
GET /uae_en/graphql
    ?hash=262598812
    &sort_1={"position":"ASC"}
    &filter_1={"price":{},"category_id":{"eq":<category_id>},"customer_group_id":{"eq":"0"}}
    &pageSize_1=<n>
    &currentPage_1=<page>
    &_currency=""
```
- `currentPage_1` works (verified pages 1/2/3 return different items).
- `pageSize_1` up to **200 confirmed working**. `1000` times out — stay ≤200.
- Response: `data.products.total_count`, `data.products.page_info{current_page,total_pages}`,
  `data.products.items[]` (see "Item fields" below).

### 2. Single product by id (full detail) — `hash=1455383406`
```
GET /uae_en/graphql
    ?hash=1455383406
    &filter_1={"id":{"eq":"<product_id>"},"customer_group_id":{"eq":"0"}}
    &pageSize_1=20
    &currentPage_1=1
    &_currency=""
```
- Same item shape as #1, **plus**: `description{html}`, `reviews`,
  `product_links`, `configurable_options[]`, `variants[]` (each a full nested
  `product` object — i.e. every color/size variant with its own images,
  price, attributes, etc.)

### 3. Category details — `hash=715881718`
```
GET /uae_en/graphql?hash=715881718&id_1=<category_id>&_currency=""
```
Returns: `name`, `description` (HTML, often contains links to subcategories),
`meta_title`/`meta_description`/`meta_keywords`, `breadcrumbs[]`,
`product_count`, `image`, banner fields, `display_mode`, etc.

### 4. Category filters/facets — `hash=1549917219`
```
GET /uae_en/graphql
    ?hash=1549917219
    &filter_1={"price":{},"category_id":{"eq":<category_id>},"customer_group_id":{"eq":"0"}}
    &_currency=""
```
Returns: `sort_fields`, `filters[]` (price buckets + presumably
color/material/etc. facets with counts), `categoryPriceRange`.

## Item field reference (from hash 262598812 / 1455383406)

```
id, sku, name, type_id (simple/configurable/bundle), stock_status, salable_qty,
price_range { minimum_price/maximum_price {
    discount{amount_off,percent_off}, final_price{value,currency},
    final_price_excl_tax, regular_price, regular_price_excl_tax,
    default_price, default_final_price, default_final_price_excl_tax
}},
media_gallery_entries[] (full image URLs at cdn2.panhomestores.com),
image / thumbnail / small_image,
short_description{html}, description{html} (detail query only),
attributes[] (attribute_code, attribute_label, attribute_value, attribute_type,
              attribute_options[{label,value,swatch_data}]),
configurable_options[], variants[] (detail query only — nested full products),
categories[] (id, name, url, breadcrumbs, product_disclaimer, warranty fields),
url, url_rewrites[], dimensions, categoryNames[], mw_canonical_url, mw_hreflangs,
reviews (detail only), review_count, rating_summary, social_proof_message
```

### ⚠️ Caveat: `attributes[].attribute_options` bloat

For multiselect attributes (notably `features`), `attribute_options` returns
the **entire catalog-wide option list** (~4,946 entries) on *every single
product response* — not just the options selected for that product. This
massively bloats response size at scale.

For full scraping:
- Fetch the `features` (and other multiselect) option dictionary
  (`attribute_id` → `[{value, label}]`) **once**, cache it separately.
- Per product, keep only `attribute_value` (comma-separated option IDs) and
  drop `attribute_options`, or strip it during ingestion.

Useful attribute codes seen on a rug product: `material_composition`,
`pile_height`, `room_type`, `cover_type`, `wood_tone`, `size` (select, 575
options — dimensions), `features` (multiselect), `gender`,
`sleep_preference`, `assembly_required`, plus modular-furniture-specific
(`modular_material`, `modular_type`, `modular_firmness`, etc.) and bundle/set
fields (`set_includes`). Color comes through as a `select` attribute with
`swatch_data` (hex value) on variant items.

### ⚠️ Caveat: `color`/`material`/`shape` (and other `select`/`multiselect`
attributes) on variant products often have **no `attribute_options` at all**
(not even an empty list) — just a raw numeric code in `attribute_value`
(e.g. `color: "22"`). The parent product's own `attributes[]` list doesn't
always include these codes either (e.g. `color` isn't a parent attribute on
configurable rugs).

To resolve these to labels (and swatches, where available), use a two-tier
lookup:

1. **Local dict** — build `attribute_code -> {value: option}` from the
   *parent* product's own `attributes[].attribute_options` (present even when
   that attribute's `attribute_value` is empty, e.g. `size`/`features` ship
   their full ~575/~4946-entry catalog-wide option list on the parent). This
   covers swatch/icon data (`swatch_data`) for free.
2. **Global dict (fallback)** — for codes still unresolved (typically
   `color`, `material`, `shape`), do a **one-time** standard POST query:
   ```graphql
   {
     customAttributeMetadata(attributes: [
       {attribute_code: "color", entity_type: "4"},
       {attribute_code: "material", entity_type: "4"},
       {attribute_code: "shape", entity_type: "4"}
     ]) {
       items { attribute_code attribute_options { value label } }
     }
   }
   ```
   `entity_type: "4"` = `catalog_product`. This is a *different* root field
   than the broken `attributes` field, works fine via standard POST, and
   returns `value`/`label` pairs (no `swatch_data` — only available via the
   per-product local dict). Cache the result and reuse across the whole
   crawl; ~205 color options, ~793 material options, ~15 shape options seen
   so far.

`test_scrape.py` implements this (`build_local_dict` + `find_missing_codes` +
`fetch_attribute_dictionary`, cached to `sample_data/attribute_dictionary.json`).

### Descriptions: parent vs. variant

For configurable products, the **parent**'s `description`/`short_description`
are typically **empty** — the real marketing copy lives on each **variant**'s
`description.html` (confirmed non-empty, several hundred chars, across all 13
sample variants; `short_description` was empty on variants too in this
sample). The parent does carry a populated `meta_description` (good fallback
/ supplementary text for the parent-level record), but `meta_description` is
**not present at all** on variant product objects.

For semantic search: use variant `description.html` as primary text per
variant, and parent `meta_description` as supplementary text for the
parent-level record.

## Category structure (relevant subset)

Full dump in [`captures/category_map.json`](captures/category_map.json). Top-level (parent_id=2)
highlights:

| id   | name              | url_path              | products |
|------|-------------------|------------------------|----------|
| 3    | Furniture         | furniture              | 23,096   |
| 4    | Accessories       | accessories            | 37,909   |
| 3403 | Outdoor & Garden  | outdoor-garden         | 1,657    |
| 3476 | Bedding Collections | bedding-collections | 4,074    |

Furniture children: Bedroom(5), Sofas(7), Living Room(8), Dining Room(6),
Home Office(9), Outdoor(10), Mattresses(11), Kids & Teens(12).

Accessories children include: Floor Covering(14), Home Decor(16, 6,420
products), Soft Furnishing(21, 5,496), Wall Decor(24, 3,265), Tabletop(22),
Lighting(19), Bathroom(13), Kitchen(18), Utility & Storage(23), Garden(15),
Kids Accessories(17), Pets Supplies(20).

**Rugs** live under Floor Covering (id=14):

| id | name              | url_path                          | products |
|----|-------------------|------------------------------------|----------|
| 87 | Rugs              | accessories/floor-covering/rugs    | 2,507    |
| 88 | Floor Accessories | accessories/floor-covering/floor-accessories | 6 |
| 89 | Floor Mats        | accessories/floor-covering/floor-mats | 228  |

## Open questions / not yet tested

- Other locales (`uae_ar`) or other country stores — these `hash` values are
  almost certainly per-locale (tied to a specific frontend build's persisted
  query registrations), so they'd need re-discovery per store code.
- Exact max `pageSize_1` between 200 and 1000 (200 is safe).
- No rate limiting observed across ~20 requests; still recommend a
  conservative delay (0.5–1s) between requests for a full crawl out of
  courtesy.
- These numeric hashes could in principle change on a future frontend
  deploy. If a full crawl starts returning persisted-query-not-found style
  errors, re-capture via `explore.py` against a live page.

## Tooling in this repo

- `capture_network.py` — interactive: you browse in a real browser window,
  it logs all XHR/fetch to `captures/<label>.json`.
- `explore.py <url> <label> [--scroll N] [--filter SUBSTRING]` — headless:
  loads a URL, optionally scrolls, captures XHR/fetch + a screenshot.
- `analyze_capture.py captures/<label>.json [--full INDEX]` — summarizes
  captured GraphQL operations (query text / hash+vars) and response shapes.
- `test_direct.py`, `test_hash_replay.py`, `test_pagination.py`,
  `build_category_map.py` — standalone scripts proving the endpoints above
  work via plain `httpx` (no browser needed for actual scraping).
