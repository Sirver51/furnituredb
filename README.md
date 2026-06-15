# Furniture DB — scraping & data exploration

## Goal

Build a database of furniture, rugs, and decor scraped from multiple UAE
retailer sites, ultimately to power a **semantic search and correlation
interface**: search by description/text, and find visually/semantically
similar items across (and within) sites.

For each target site, we've reverse-engineered how to fetch product listings
and full product detail (description, attributes, images) via plain HTTP — no
browser needed for the actual scrape, just for the initial recon. A **Phase 1
sample crawl** (~100 products/category, every category) populates
`raw/products/` for all 3 sites, with images streamed to `aria2c`; a **Phase 2**
complete crawl of selected categories (e.g. Rugs) reuses the same machinery.

> Designing against the raw data? See
> [`docs/db_ui_handoff.md`](docs/db_ui_handoff.md) for the on-disk layout, raw
> record shapes per site, and cross-site normalization notes.

## Ground rules established so far

- Python deps go through a **uv-managed `.venv`** (`uv add <pkg>`,
  `uv run python ...`).
- Per-site work lives under `sites/<site>/`; reusable tooling lives at the repo
  root (`common/`).
- Run `uv run python summarize_raw.py` for per-site status (categories done,
  product/image counts, disk usage).

## Repo layout

```
furnituredb/
├── pyproject.toml / uv.lock        # deps: httpx, playwright, beautifulsoup4, bs4
├── common/                          # shared crawl infra
│   ├── pacing.py                    # polite_delay(site) - jittered per-site delay
│   ├── aria2.py                     # aria2c JSON-RPC client (add_download)
│   └── storage.py                   # save/load_json, product_path, CrawlState
├── summarize_raw.py                 # per-site progress/disk-usage report
├── capture_network.py              # interactive browser capture (manual)
├── explore.py                      # headless browser capture (automated)
├── analyze_capture.py              # summarize a capture JSON
├── docs/db_ui_handoff.md            # raw data reference for DB/UI session
└── sites/
    ├── panhome/                    # panhomestores.com (Magento, GraphQL)
    ├── homecentre/                 # homecentre.com (Bloomreach + custom REST)
    └── homesrus/                   # homesrus.ae (Magento, HTML-only)
```

Each `sites/<site>/` contains:
- `API_NOTES.md` — full writeup of the reverse-engineered API/data sources for
  that site (the canonical per-site reference).
- `captures/` — raw network captures (JSON/screenshots) from `explore.py` /
  `capture_network.py`, used during recon.
- `api.py` — HTTP/GraphQL helpers + image-queueing, shared by the crawl scripts.
- `crawl_categories.py` — (re)builds `raw/categories.json`.
- `crawl_sample.py` — Phase 1: samples ~100 products/category, resumable via
  `raw/crawl_state.json`.
- `crawl_rugs.py` — Phase 2: complete crawl of the Rugs category.
- `raw/products/<shard>/<key>.json` + `images/<dir>/...` — output (see
  `docs/db_ui_handoff.md` for exact shapes).

## Generic tooling (repo root)

- **`explore.py <url> <label> [--scroll N] [--filter SUBSTRING] [--outdir DIR]`**
  Headless: loads a URL, optionally scrolls, captures all XHR/fetch
  request+response pairs to `<outdir>/<label>.json`, plus a screenshot
  `<outdir>/<label>.png`. Default `--outdir` is `captures/`; use
  `--outdir sites/<site>/captures` for per-site captures.

- **`capture_network.py <url> <label> [--filter SUBSTRING] [--outdir DIR]`**
  Interactive: opens a real (non-headless) browser, you click around manually,
  press Enter in the terminal to stop. Same output format as `explore.py`.

- **`analyze_capture.py captures/<label>.json [--full INDEX]`**
  Summarizes a capture: lists GraphQL operations (query text / persisted-query
  hash + variables) and the shape of each JSON response, without dumping huge
  bodies. `--full INDEX` dumps one entry in full.

Both capture tools wrap `request.post_data` in try/except — some sites
(Magento + analytics beacons) send gzip-compressed POST bodies that crash
Playwright's UTF-8 decode otherwise.

## Data model differences (for DB schema design)

See [`docs/db_ui_handoff.md`](docs/db_ui_handoff.md) for the full field-level
reference (with real examples from `raw/products/`) and cross-site
normalization notes (color, material, dimensions, taxonomy, price, images).

## Open questions / not yet explored

- Cross-site attribute normalization (e.g. unifying "color", "material",
  "shape" vocabularies across all three sites) — see `docs/db_ui_handoff.md`.
- Embedding/indexing approach for semantic search — see
  [`docs/db_strategy.md`](docs/db_strategy.md).
