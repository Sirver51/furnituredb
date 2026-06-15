# Homes R Us (UAE) — API Notes

Site: https://www.homesrus.ae/en/
Platform: Magento 2 (Ktpl/homerus theme) + Amasty layered navigation + a custom
search module (`ev_route`). **No GraphQL** — `/graphql` and `/en/graphql` both
return 500 errors, and the homepage references no GraphQL endpoints at all.

## TL;DR

- No login/cookies/session needed. Plain `httpx` GETs work for everything below.
- There is **no JSON product-listing API**. Listing/search results come back as
  a pre-rendered **HTML fragment inside a JSON wrapper**; product *detail* pages
  are plain server-rendered HTML with rich embedded JSON (`<script>` tags).
- Each color/size variant is its own **separate simple product** (own sku, own
  URL, own page) — there's no parent/configurable/variant grouping to resolve,
  unlike Panhome and Home Centre.
- Added `beautifulsoup4` (`uv add beautifulsoup4`) to parse the HTML pieces.

## 1. Search / listing — `ev_route/search/jsonresponse`

```
GET https://www.homesrus.ae/en/ev_route/search/jsonresponse/?q=<term>&p=<page>
```

- `q` — search term (e.g. `rug`). Also works as a general "browse by keyword"
  endpoint — no separate category-tree API was found, so this is the practical
  entry point for pulling a set of products.
- `p` — 1-based page number. Page size is fixed at **48** (confirmed `p=1` and
  `p=2` return different items).
- Response: `{"result": "<html fragment>"}` — a big HTML string containing the
  filter sidebar (with category facets + counts) and the product grid.

### Parsing the fragment (BeautifulSoup)

```python
soup = BeautifulSoup(resp.json()["result"], "html.parser")

for item in soup.select("li.item.product.product-item"):
    link = item.select_one("a.product-item-link")     # .get_text() = name, ["href"] = product URL
    sku  = item.select_one("[data-product-sku]")["data-product-sku"]
    img  = item.select_one("img.product-image-photo")["src"]
    price_text = item.select_one(".price-box").get_text(" ", strip=True)
    # e.g. "Special Price AED 90.00 Regular Price AED 129.00 (Save 30%)"
```

- Total result count: `soup.select_one(".toolbar-amount")` →
  `"Items 1 - 48 of 272 results for this search"`.
- For clean price data, prefer the JSON-LD `offers.price` on the product detail
  page (below) over parsing `.price-box` text.

## 2. Product detail — plain HTML page

```
GET <product url>   (e.g. https://www.homesrus.ae/en/5110200103823-duncan-rug-multicolor-80x150cm/)
```

Everything needed is embedded as JSON inside `<script>` tags — no extra
requests needed per product.

### a) JSON-LD `Product` (`<script type="application/ld+json">`)
```json
{
  "@type": "Product",
  "name": "Duncan Rug, Multicolor - 80x150cm",
  "image": "https://www.homesrus.ae/media/catalog/product/5/1/5110200103823_0.jpg?...",
  "description": "Add a touch of contemporary elegance to your living space...",
  "sku": "5110200103823",
  "brand": {"@type": "Brand", "name": "Homes r Us UAE"},
  "offers": {"price": 90.0, "priceCurrency": "AED", "availability": "https://schema.org/InStock", ...},
  "aggregateRating": {"ratingValue": "4.5", "ratingCount": "87"}
}
```
- `description` is plain text, fully populated.
- `image` may contain `&amp;` — run through `html.unescape()`.
- `offers.price` reflects the **current** (sale) price.

### b) JSON-LD `BreadcrumbList` (separate `<script type="application/ld+json">`)
`itemListElement[]` → `[{"name", "item": <url>}, ...]` gives the full category
path (e.g. Home → Household → Décor and Furnishings → Floor Coverings → ...).
Names may contain `&amp;` — unescape.

### c) Image gallery — `<script type="text/x-magento-init">`
One of these blocks contains the `mage/gallery/gallery` widget config:
```json
{
  "[data-gallery-role=gallery-placeholder]": {
    "mage/gallery/gallery": {
      "data": [
        {"img": "https://www.homesrus.ae/media/catalog/product/.../5110200103823_0.jpg?...",
         "isMain": true, "type": "image", "position": "0", ...},
        ...
      ]
    }
  }
}
```
- `data[].img` gives full-res URLs for **every** product image (the
  `<div data-gallery-role="gallery-placeholder">` in the HTML itself only shows
  the single main image — the rest only exist in this JSON).
- Filter `type == "image"` (there can also be `type: "video"` entries).

### d) Specs — `<ul class="product-attribute-list">`
```html
<li class="col label"><span>Country of Manufacture: </span><span class="col data">India</span></li>
```
Each `<li>` has two `<span>`s: label and value. Already human-readable
(`Primary material`, `Item Length`, `Item Width/Depth`, `Care Maintenance`,
`Net Weight (Kg)`, etc.) — no code/label dictionary needed.

## Images

CDN: `https://www.homesrus.ae/media/catalog/product/<a>/<b>/<sku>_<n>.jpg?...` —
public, no auth. Query params (`width`, `height`, `quality`, `fit`, etc.) are
resize parameters; the bare URL (no query string) also works.

## Open questions / not yet tested

- No category-tree endpoint found — `q=<term>` against `ev_route/search/jsonresponse`
  is the only listing mechanism identified. A broad/empty `q` or category-id-based
  query might exist but wasn't explored.
- Max `p` / total pages behavior at the end of a result set.
- Whether `swatch-attribute`/configurable products exist anywhere on the site
  (none seen in the rug sample — every variant so far is its own simple product).
- Rate limiting at scale. `robots.txt` declares `Crawl-delay: 10` site-wide
  (pages + images, same host) — see `common/pacing.py` for the crawler's actual
  (gentler-than-literal-compliance) delay.

## Tooling notes

- `explore.py` / `capture_network.py` were patched this session: `request.post_data`
  raised `UnicodeDecodeError` on gzip-compressed POST bodies (seen on this site's
  analytics calls) — now wrapped in try/except so captures don't crash.
- Added `beautifulsoup4` as a project dependency for HTML parsing.
