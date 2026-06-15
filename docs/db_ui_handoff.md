# Raw data reference for DB schema + UI work

A reference for designing the DB schema and UI against the scraped data. For
*how the data was obtained* (API endpoints, persisted-query hashes, etc.) see
each site's `sites/<site>/API_NOTES.md` — this doc is about *the shape of what's
on disk* and how to consume it.

Run `uv run python summarize_raw.py` from the repo root for current per-site
counts/sizes.

> The crawls grow over time (Phase 1 sample crawl, then a Phase 2 complete crawl
> of selected categories), all writing the **same file shapes** described below.
> The schema should not assume any particular product counts are final. All
> crawls are resumable (`raw/crawl_state.json` tracks completed categories), so
> re-running `crawl_sample.py` just continues. Homes R Us is intentionally slow
> (3-5s/request) and stays small for a while.

## Raw data layout (same shape for all 3 sites)

```
sites/<site>/
├── raw/
│   ├── categories.json        # category list this site's Phase 1 iterates over
│   ├── crawl_state.json        # {"categories_done": ["<key>", ...]}
│   ├── image_manifest.jsonl     # one {"url": ..., "dest": "images/..."} per queued image
│   ├── listings/<cat>/page_*.json   # raw listing/search responses (for reference only)
│   └── products/<shard>/<key>.json  # ONE JSON FILE PER PRODUCT - see per-site shapes below
└── images/<dir>/<filename>      # downloaded via aria2c; <dir> naming varies by site (see below)
```

`<shard>` = first 2 characters of `<key>` (just a directory-fan-out, not
semantically meaningful). `<key>` differs by site — **this is the most
important per-site difference for ingestion**, see below.

## Per-site product record reference

### Panhome — `sites/panhome/raw/products/<id>.json`

`<key>` = Magento numeric product **id** (e.g. `14226.json`). One file per
product *and* per variant-of-a-configurable (variants are also nested inside
their parent's file — see below).

Top-level fields of interest:
- `id`, `sku`, `name`, `type_id` (`"simple"` or `"configurable"`),
  `stock_status`, `salable_qty`
- `price_range.minimum_price` / `.maximum_price` → `.regular_price.value`,
  `.final_price.value`, `.discount.{amount_off,percent_off}`, `currency`
  (AED). For simple products min==max.
- `description.html`, `short_description.html` — **often empty on
  configurable parents**; real copy lives on each variant's `product.description.html`.
- `meta_description`, `meta_title` — good fallback copy for configurables.
- `media_gallery_entries[]` — `{file, position, base.url, ...}`. Image files
  live at `https://cdn2.panhomestores.com/media/catalog/product<file>`, and
  are downloaded to `images/<sku>/<basename(file)>`.
- `attributes[]` — `[{attribute_code, attribute_label, attribute_value,
  attribute_type, attribute_options[]}]`. For `select`/`multiselect` types,
  `attribute_options` gives `{label, value, swatch_data}` for *this product's*
  chosen value(s) — usually enough to resolve without the dictionary. Codes
  not covered fall back to `raw/attribute_dictionary.json` (global
  code→label dict, built/extended by `build_attribute_dictionary.py`, only
  partially populated so far).
- **De-bloat**: any `attribute_options` array >50 entries (the catalog-wide
  `features` multiselect, ~4,946 options) is stripped down to just the
  product's selected option(s) before saving — the full dictionary lives
  separately in `attribute_dictionary.json`.
- `categories[]` — full breadcrumb-annotated list, but **includes
  promotional/cross-listing categories** (Sale, Discount 30-50%, Last Chance,
  Additional 10%, etc.) alongside the "real" taxonomy (Accessories > Soft
  Furnishing > Duvets & Pillows > Pillows). `categoryNames[]` is the flat
  parallel list (with dupes). For a clean taxonomy path, prefer the
  longest/deepest non-promotional `breadcrumbs` chain, or cross-reference
  against `raw/categories.json` (leaf categories used for crawling, all
  non-promotional).
- `configurable_options[]` (parent only) — which attribute(s) vary across
  variants (almost always `color`), referencing `attribute_options` by
  `value_index`.
- `variants[]` (parent only, `type_id="configurable"`) — each
  `{product: {<full nested product, same shape as a simple product
  including its own id/sku/name/description/media_gallery_entries/attributes/price_range>}}`.
  **Each variant is also itself saved as its own top-level
  `raw/products/<variant_id>.json` file** (e.g. parent `14226.json` has a
  variant with `id=14218`, also present as `raw/products/14/14218.json`).
  So variants are NOT duplicated data you need to extract — they're
  independently-keyed records; the parent's `variants[]` is just a
  convenience grouping/pointer.
- Images on disk: `images/<sku>/<filename>` — separate dirs per
  variant-sku AND per parent-sku (parent's own `media_gallery_entries`, if
  any, vs each variant's).

### Home Centre — `sites/homecentre/raw/products/<pid>.json`

`<key>` = the **pid** encountered during category search (this is a
*color-variant* SKU, e.g. `112809648`, NOT the parent's `sku` field).

**Important gotcha**: the saved record is always the FULL parent+variants
record, regardless of which color's pid triggered the fetch. So if 3 colors
of the same product were sampled, you get **3 files with identical content**
(`112809648.json`, `145167143.json`, `155131101.json`, ...), each containing
the same top-level `id` (a ULID) and the same `variants[]` array. **Dedupe by
top-level `id`** when loading into the DB — don't treat each file as a
distinct product.

Top-level fields of interest:
- `id` (ULID, **the real unique product id**), `sku` (parent sku, often
  `<a-pid>-<styleSuffix>`, e.g. `112809736-HCB33AUG15`), `name`,
  `productType` (`"VARIANT_BASED"` when it has color variants).
- `priceInfo.price.{amount,currency}` (currency AED), `priceInfo.priceType`.
- `description` — plain string with embedded `</br>`/`<b>` HTML tags.
  `metaDescription`, `metaTitle`.
- `breadcrumbs[]` — `[{label, uri}]`, clean taxonomy path, last entry is the
  product itself (no `uri`). Also `concept`/`conceptGroup`/`conceptDepartment`/
  `conceptClass`/`conceptSubclass` give a parallel internal taxonomy.
- `brand.displayValue` (almost always `"Home Centre"`).
- `options[]` — variant-distinguishing attributes, e.g. `Color`/`ShadeColor`,
  each with `allowedValues[]` = `[{label, value}]` where `value` is the
  variant's pid/sku.
- `variants[]` — one per color, `{sku, defaultPrice, salePrice,
  optionValues: {Color: "<sku>", ShadeColor: "<sku>"}, ...}`.
- `assets[]` — **all images for all colors**, each
  `{url, tags: ["color:<sku>"], primary, type:"IMAGE"}`. Filter by
  `color:<variant-sku>` to get one color's gallery. `primaryAsset` is the
  default. Images downloaded to `images/<variant-sku>/<filename>` (grouped by
  the `color:` tag, falling back to parent `sku` for assets with no color
  tag).
- `productAttributeDetails[]` — grouped human-readable specs:
  `[{groupName, groupDisplayName, style, attributeDetails: {<key>:
  {value, nameLabel}}}]` (groups seen: `weightDimensions`, `Material`,
  `generalSpecifications`, `warrantyCare`, `assembly`). `attributes[]` is the
  same data flattened: `[{nameLabel, value}]`. **Already human-readable —
  no code/dictionary resolution needed**, unlike Panhome.

### Homes R Us — `sites/homesrus/raw/products/<sku>.json`

`<key>` = the 13-digit product **sku** (e.g. `5110600305209.json`). **No
variant grouping at all** — every color/size is its own fully independent
record with its own sku/url/page. Simplest shape of the three:

- `url`, `sku`, `name`, `description` (plain text).
- `image` — single representative image URL (CDN, with resize query params).
- `brand.name`.
- `offers.{price, priceCurrency, availability, itemCondition, priceValidUntil}`.
- `aggregateRating.{ratingValue, ratingCount, bestRating, worstRating}` —
  present on some products, absent on others.
- `breadcrumbs[]` — `[{name, url}]`, clean taxonomy path, **last entry is the
  product itself** (its `url` == this product's `url`).
- `specs` — flat dict of human-readable specs, e.g. `{"Country of
  Manufacture": "China", "Primary material": "Plastic", "Item Length": "8cm",
  "Item Height": "24cm", "Care Maintenance": "..."}`. Keys vary by product —
  no fixed schema.
- `gallery[]` — full list of image URLs (CDN, with resize query params).
  Downloaded to `images/<sku>/<filename>` (filename derived from the URL
  path, query params stripped).

## Cross-site data model differences (for schema design)

| | Panhome | Home Centre | Homes R Us |
|---|---|---|---|
| Unique product id | `id` (int, Magento) — variants are separate ids/records | `id` (ULID) — **dedupe across files by this**, not filename | `sku` (13-digit) — also the filename/dedupe key |
| Variant grouping | parent (`type_id=configurable`) + `variants[]`, each variant is *also* its own top-level record | parent record (any of its color-pid files) has `variants[]` = price/sku per color; images split via `assets[].tags` | none — every color/size is a fully separate record, no link between them |
| Description location | per-**variant** `description.html` (parent's often empty); `meta_description` as fallback | top-level `description` (shared across colors) | top-level `description` |
| Price | `price_range.{minimum,maximum}_price.*` (AED), incl. discount % | `priceInfo.price.amount` (AED) at top level + per-variant `defaultPrice`/`salePrice` | `offers.price` + `offers.priceCurrency` |
| Attributes | `attributes[]`, coded (`select`/`multiselect` with `attribute_options` resolving most; rest via `attribute_dictionary.json`) | `productAttributeDetails[]` (grouped) / `attributes[]` (flat) — fully human-readable | `specs` — flat dict, free-form keys, human-readable |
| Categories/taxonomy | `categories[]` / `categoryNames[]` — polluted with promo rollups (Sale, Discount, etc.) | `breadcrumbs[]` (clean) + `concept*` fields | `breadcrumbs[]` (clean), last entry = product itself |
| Images | `media_gallery_entries[]`, per parent AND per variant, → `images/<sku>/` | `assets[]` shared across colors, tagged `color:<sku>`, → `images/<variant-sku>/` | `gallery[]`, → `images/<sku>/` |
| Currency | AED everywhere (all 3 sites, UAE storefronts) | AED | AED |

**Common normalization challenges to expect:**
- Attribute naming across sites for the same concept, e.g. "material":
  Panhome `attribute_code="material"` (coded, needs dictionary), Home Centre
  `primaryMaterial`/`primaryMaterialType`/`materialFinish` (human-readable),
  Homes R Us `specs["Primary material"]` (free-form string key).
- "Color": Panhome coded `color` attribute w/ swatch hex; Home Centre
  `options[]` with `Color`/`ShadeColor` (label + hex-free); Homes R Us — no
  structured color field, it's baked into `name`/`specs` if present at all.
- Dimensions: Panhome — often only in `name` (e.g. "45x70x13cm") or
  `dimensions` (JSON string, sparse); Home Centre — structured
  `widthCM`/`lengthCM`/`heightCM` in `productAttributeDetails`; Homes R Us —
  free-form `specs["Item Length"]`/`["Item Height"]` etc, units embedded in
  the string.
- All three sites' raw JSON should be treated as the **source of truth /
  archival layer** — the DB schema should be a normalized projection of this,
  not a 1:1 mirror.

## Useful scripts

- `uv run python summarize_raw.py [site ...]` — counts/sizes per site (run
  from repo root).
- `sites/<site>/raw/categories.json` — the category list (path/slug + known
  `product_count` where available) used for Phase 1; useful as a starting
  taxonomy reference even before products finish crawling.
- Each site's `API_NOTES.md` has the full reverse-engineered API reference if
  you need to fetch anything not already on disk.
