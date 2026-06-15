# Database strategy & schema

Decision record + schema for the data and vector storage layers. Companion to
[`db_ui_handoff.md`](db_ui_handoff.md) (raw record shapes) — this doc is about
*how the normalized, queryable layer is structured* and *why*.

Status: **core pipeline implemented and validated.** Ingestion (`db/ingest.py`)
projects the raw per-site JSON into `furniture.db`; the embedding pipeline
(`db/embed.py` + `db/embeddings/`) embeds curated text docs and per-image
vectors via Gemini, idempotently. Both are designed to scale to the full corpus
incrementally (re-runs only touch changed content). Current run counts are
tracked separately, outside this design doc.

## Decisions (locked)

| Concern | Choice |
|---|---|
| Canonical data store | **SQLite** (single file, no server) |
| Lexical / keyword search | **SQLite FTS5** (built in) |
| Vector store | **sqlite-vec**, behind a thin interface so it can be swapped |
| Embedding model | **Gemini Embedding 2** (natively multimodal — one shared text+image space) |
| Search model | **Hybrid from day one**: FTS5 (BM25) + vector KNN, fused |

Everything lives in **one SQLite database file** (data + FTS + vectors via the
sqlite-vec extension). One artifact to back up, copy, or ship.

## Why these engines

### SQLite for the canonical data
Local, single-user research tool — a Postgres/pgvector server buys nothing here.
The data is genuinely relational (product ↔ variant ↔ image ↔ attribute ↔
category), which is exactly the normalized projection described in the handoff
doc. The raw `raw/products/**.json` remains the archival source of truth; this
DB is a derived, rebuildable projection.

### FTS5 for lexical search
Semantic search alone under-performs on exact terms — SKUs, "teak", "150x200",
brand names. FTS5 (BM25) is in-engine, free, and complements the vector side.
Required because hybrid is a day-one decision.

### sqlite-vec for vectors — with eyes open
sqlite-vec does **brute-force KNN** (no ANN index). That is exact and tuning-free,
and fine at our scale:

| Vector set | Realistic count | Verdict |
|---|---|---|
| Text (product-level) | tens of thousands (dedup'd) | trivial, <10 ms |
| Image (per-image) | ~300K now → up to ~1M after full crawls | the pressure point: ~100–300 ms/query at 768–1536-d |

~100–300 ms for a local "find similar" is acceptable. **Image vectors are the
only thing that could eventually justify a dedicated ANN store** (see migration
trigger below). We do *not* introduce a server-based vector DB
(Qdrant/Chroma/Milvus) — that throws away the one-file, zero-infra property for
no current benefit.

## Embeddings: Gemini Embedding 2

Model id: **`gemini-embedding-2-preview`** (public preview). Natively
multimodal → **text and images land in the same vector space**, so cross-modal
queries work directly: a text query can rank images, an image query can rank
products, etc. This is what makes the README's "find visually / semantically
similar" goal cheap to build.

Because it's an **API model** (not local), two properties are non-negotiable in
the pipeline design:

1. **Idempotent embedding.** Embeddings cost money and are rate-limited. Each
   embeddable unit carries a `content_hash`; we only (re)embed when the hash
   changes. Re-running ingestion must not re-embed unchanged content.
2. **Durable persistence.** Embeddings are stored in the DB, never recomputed on
   the fly. A full re-embed is a deliberate, tracked operation (model upgrade),
   gated by `embedding_meta`.

### Call pattern: sync `batchEmbedContents`, NOT async Batch Mode

Two different "batch" things exist in the Gemini API — easy to conflate:

- **Batch Mode** (async job, 50% price, target 24h turnaround). **Rejected** —
  too slow for this pipeline's iteration loop.
- **`batchEmbedContents`** (sync REST/SDK method): a single HTTP call carrying a
  **list of independent `EmbedContentRequest` objects**, returning **one
  embedding vector per request** (no fusion). Standard sync pricing/latency,
  just amortized over many inputs per round-trip. **This is what we use.**

A request with **mixed text+image parts produces ONE fused vector** — that
fusion behavior is irrelevant here because every request in our batches is
**single-modality** (one product-text doc, or one image) by design (see below).
The per-request image cap (6 images) therefore never applies — each image is its
own request.

Practical batch size (how many requests per `batchEmbedContents` call) and
concurrency are `EmbeddingProvider` config (default batch size 25). Tuned
empirically against the live per-key rate limits:

- The binding constraint is **`embed_content_input_tokens_per_minute_per_base_model`**
  — a token budget shared across the *entire* API key/project for
  `gemini-embedding-2-preview`, refilling every 60s. It is **not** sensitive to
  batch size or process count: observed throughput for image batches was ~25
  images per ~55-60s regardless.
- **Running multiple `db.embed` processes in parallel for images livelocks**:
  each process's batch call exhausts the shared per-minute budget just as the
  others wake from their 429 backoff, so none make progress. Run image
  embedding **sequentially** (one site at a time); text embedding is cheap
  enough per-request that parallel text runs are fine.
- `db/embeddings/provider.py`'s `_embed_chunk` retries 429/500/503 up to 8
  times; for 429 specifically it waits `60s * uniform(0.8, 1.3)` (jittered, to
  desync any concurrent callers) rather than exponential backoff, since the
  quota is a fixed per-minute window, not a transient overload.

### What gets embedded: separate text + per-image vectors

Per product:

- **One text vector** (`vec_text`, keyed by `product_id`) from a **curated
  product document** — not a raw field dump. Include: `name`, cleaned
  `description`, and a *selected* subset of canonical specs (material, color,
  shape/style, room/use, a one-line dimension summary, brand, `taxonomy_path`).
  Exclude: SKU, URLs, raw IDs, price, availability, ratings, warranty/care
  boilerplate, country-of-manufacture — those are filters/FTS terms, not
  semantic content. (The FTS5 `specs` column still gets *all* specs — lexical
  match is precise and cheap, so the split costs nothing.)
- **One vector per distinct image** (`vec_image`, keyed by `image_id`),
  embedded **image-only** (no fused text) — enables true per-photo visual
  similarity and cross-site "this exact photo looks like…" matching. Because
  the space is shared, these are still findable by text queries.
- **Dedup before embedding**: `db/embed.py` groups images by `content_hash`
  before calling the API — both *within* a run (two images sharing a hash for
  the first time embed once, vector copied to both) and *across* runs (a hash
  already present in `embedding_state` has its vector copied via
  `VectorStore.get()`, no API call). Handles Home Centre's shared `assets[]`
  across color files and Panhome's repeated parent/variant images.
- **Image scope per run**: no per-product cap by design — `db.embed` will embed
  every distinct gallery image. Given the per-minute quota (see above), a
  `--primary-only` mode embeds just one representative image per product
  (`is_primary`, else lowest position/id) to make an early pass tractable; the
  remaining secondary/variant images are then a `db.embed --modality image`
  (without `--primary-only`) backfill.

### Dimensionality
Gemini embeddings are large and **Matryoshka-truncatable** (a prefix of the
vector is still a valid embedding). Brute-force cost and storage scale linearly
with dimension over ~1M image vectors:

| Dim | Bytes/vector | ~1M image vectors |
|---|---|---|
| 768 | 3 KB | ~3 GB |
| 1536 | 6 KB | ~6 GB |
| 3072 (full) | 12 KB | ~12 GB |

**Recommendation: one uniform truncated dimension across both modalities**
(default **768**; bump to 1536 if retrieval quality demands it). Uniform dim
keeps cross-modal search trivial — text-query and image-target vectors must share
dimensionality to be comparable, and truncation preserves the prefix so a
truncated query matches truncated targets. The chosen dim is recorded in
`embedding_meta`; the `FLOAT[768]` in the schema below must match it.

> Note: exact model id, default dim, and whether image input is bytes vs. a
> reference are Gemini API details to confirm at implementation time — they don't
> affect the schema beyond the dimension constant.

## Thin interfaces (swap insurance)

Two narrow seams isolate the swappable parts, implemented in `db/embeddings/`.

- **`EmbeddingProvider`** (`db/embeddings/provider.py`) — `embed_texts([str])
  -> [vector]`, `embed_images([(bytes, mime)]) -> [vector]` (each a
  `batchEmbedContents` call, one vector per input, with internal
  chunking/backoff), plus `model_id` / `dim` / `normalized`. Concrete impl:
  `GeminiEmbeddingProvider` (Gemini Embedding 2). Isolates us from the
  embedding vendor and makes a model upgrade a single-file change + a tracked
  re-embed.

- **`VectorStore`** (`db/embeddings/store.py`) — `upsert(id, vector)`,
  `get(id) -> vector | None`, `search(vector, k) -> [(id, distance)]`, per
  modality. Concrete impl: `SqliteVecStore` (sqlite-vec). **This is the seam
  that makes a LanceDB migration mechanical** if image-vector count ever
  outgrows brute force.

Application/search code depends only on these contracts, never on sqlite-vec or
Gemini APIs directly.

## Hybrid search design

Two retrievers, fused — run for every query:

1. **Lexical** — FTS5 BM25 over `name` + `description` + flattened `specs`.
2. **Semantic** — Gemini-embedded query vector → `VectorStore.search` against
   `vec_text` (product-level) and/or `vec_image` (image-level).

**Fusion: Reciprocal Rank Fusion (RRF)** — rank-based, no score normalization
across heterogeneous scales, robust default. A weighted-score blend is a later
tuning option.

Query modes this enables:
- text → products (lexical + semantic text)
- text → images (semantic, cross-modal)
- image → similar images / products (semantic, cross-modal, via `vec_image`)
- all of the above filterable by structured columns (site, price, canonical
  attributes, taxonomy) — the relational layer does the filtering, vectors do
  the ranking.

## Schema

One SQLite file. DDL below; sqlite-vec virtual tables require the extension
loaded. The model: **one row per buyable unit (variant level)** with a
self-link for grouping — the only model that absorbs all three sites uniformly.

```sql
-- ── canonical buyable item (variant-level) ────────────────────────────────
-- One row per distinct sellable SKU/variant. Standalone products are a group
-- of one.
CREATE TABLE product (
  id              INTEGER PRIMARY KEY,
  site            TEXT    NOT NULL,        -- 'panhome' | 'homecentre' | 'homesrus'
  source_id       TEXT    NOT NULL,        -- dedupe key: panhome int id / HC ULID / HRU sku
  source_key      TEXT    NOT NULL,        -- raw filename stem
  group_key       TEXT,                    -- parent/configurable id; NULL or =source_id if standalone
  is_group_parent INTEGER NOT NULL DEFAULT 0,  -- panhome configurable / HC parent record
  sku             TEXT,
  name            TEXT    NOT NULL,
  description     TEXT,                    -- cleaned to plain text/markdown
  brand           TEXT,
  url             TEXT,
  currency        TEXT    DEFAULT 'AED',
  price           REAL,                    -- final/effective price
  regular_price   REAL,
  discount_pct    REAL,
  availability    TEXT,
  rating_value    REAL,
  rating_count    INTEGER,
  taxonomy_path   TEXT,                    -- denormalized clean breadcrumb, '/'-joined
  raw_path        TEXT    NOT NULL,        -- pointer back to archival JSON
  content_hash    TEXT    NOT NULL,        -- idempotent re-ingest + re-embed gate
  crawled_at      TEXT,
  ingested_at     TEXT,
  UNIQUE (site, source_id)                 -- the dedupe contract (HC ULID dupes, etc.)
);
CREATE INDEX idx_product_group ON product(site, group_key);
CREATE INDEX idx_product_price ON product(price);

-- ── images (per-image; visual search keys off these) ──────────────────────
CREATE TABLE image (
  id           INTEGER PRIMARY KEY,
  product_id   INTEGER NOT NULL REFERENCES product(id),
  url          TEXT    NOT NULL,
  local_path   TEXT,                       -- images/<dir>/<file>, NULL until downloaded
  position     INTEGER,
  is_primary   INTEGER NOT NULL DEFAULT 0,
  color_tag    TEXT,                       -- HC 'color:<sku>'; NULL elsewhere
  content_hash TEXT,                        -- re-embed gate for image vectors
  UNIQUE (product_id, url)
);
CREATE INDEX idx_image_product ON image(product_id);

-- ── attributes (EAV: keep raw AND canonical) ──────────────────────────────
-- name_canonical/value_canonical are the cross-site normalization layer
-- (material/color/dimensions); raw is preserved untouched.
CREATE TABLE attribute (
  id              INTEGER PRIMARY KEY,
  product_id      INTEGER NOT NULL REFERENCES product(id),
  name_raw        TEXT NOT NULL,           -- 'Primary material' / 'material' / 'primaryMaterialType'
  name_canonical  TEXT,                    -- 'material'
  value_raw       TEXT,
  value_canonical TEXT,
  unit            TEXT                      -- for dimensions, where extractable
);
CREATE INDEX idx_attr_product ON attribute(product_id);
CREATE INDEX idx_attr_canon   ON attribute(name_canonical, value_canonical);

-- ── lexical search ────────────────────────────────────────────────────────
-- Standalone (not external-content): specs is derived (no matching `product`
-- column), and rowid is set explicitly to product.id on insert.
CREATE VIRTUAL TABLE product_fts USING fts5(name, description, specs);

-- ── vectors (sqlite-vec). Same Gemini space; separate tables by key grain. ──
-- Dimension MUST match embedding_meta.dim (default 768).
CREATE VIRTUAL TABLE vec_text  USING vec0(product_id INTEGER PRIMARY KEY, embedding FLOAT[768]);
CREATE VIRTUAL TABLE vec_image USING vec0(image_id   INTEGER PRIMARY KEY, embedding FLOAT[768]);

-- ── embedding provenance (gates full re-embeds on model change) ───────────
CREATE TABLE embedding_meta (
  modality   TEXT NOT NULL,               -- 'text' | 'image'
  model      TEXT NOT NULL,               -- e.g. gemini embedding 2 id
  dim        INTEGER NOT NULL,
  normalized INTEGER NOT NULL DEFAULT 1,
  created_at TEXT,
  PRIMARY KEY (modality, model)
);

-- ── embedding gate: content hash of the input last embedded for this ref ──
-- ref_id is product.id for kind='text', image.id for kind='image'. Re-embed
-- only when the current hash differs from what's stored here.
CREATE TABLE embedding_state (
  kind         TEXT    NOT NULL,          -- 'text' | 'image'
  ref_id       INTEGER NOT NULL,
  content_hash TEXT    NOT NULL,
  PRIMARY KEY (kind, ref_id)
);
```

v1 implementation note: the separate `category`/`product_category` faceted-browse
tables from the original design are deferred — `taxonomy_path` (denormalized
breadcrumb string) covers v1 filtering/display needs. Revisit if faceted browse
becomes a UI requirement.

### How the schema maps to each site

- **Dedupe** is enforced by `UNIQUE(site, source_id)`. This directly absorbs the
  Home Centre "3 identical files share one ULID" trap (handoff doc) — `source_id`
  = the ULID, so the duplicate color-pid files collapse to one row.
- **Variant grouping** via `group_key` + `is_group_parent`:
  - *Panhome*: each variant id is its own `product` row; `group_key` = parent
    configurable id; the configurable parent is a row with `is_group_parent=1`.
  - *Home Centre*: each color variant sku is a `product` row; `group_key` = the
    parent ULID.
  - *Homes R Us*: no grouping — each sku is a standalone row, `group_key` NULL.
- **Description location** differs per site (Panhome: per-variant; HC/HRU:
  top-level) — resolved during ingestion into the single `description` column;
  Panhome's `meta_description` is the fallback when a variant's copy is empty.
- **Images** are per-image rows so `vec_image` can rank individual photos and do
  true cross-site visual matching; HC's `color:<sku>` tag is preserved in
  `color_tag`.
- **Attributes**: raw kept verbatim; `*_canonical` populated incrementally as the
  cross-site vocabulary (material/color/dimensions) is built out.

### Idempotent ingestion contract
- A product row is keyed by `(site, source_id)`; re-ingest is an upsert.
- `embedding_state` records the content hash last embedded for each
  `(kind, ref_id)` (`kind` = 'text' → `product.id`, 'image' → `image.id`).
  `db/embed.py` recomputes the hash of the current input (curated text doc /
  image bytes) and skips the Gemini call when it matches AND a vector already
  exists in the corresponding `vec_*` table.
- A model change is recorded in `embedding_meta` and is the only thing that
  forces a full re-embed.

### Embedding cache/backup (JSON export)

`db/export_embeddings.py` snapshots `vec_text`/`vec_image` (+ their
`embedding_state` hashes) to `data/embeddings/{text,image}.jsonl` — one JSON
object per line: `{ref_id, hash, vector_b64}` (float32 vector, base64-encoded).
Purpose: avoid re-calling the embedding API if the sqlite-vec tables ever need
rebuilding (dimension/model change, DB corruption, schema migration). Restore
by base64-decoding `vector_b64` back to float32 bytes and inserting into the
matching `vec_*` table plus `embedding_state`. Run via `uv run python -m
db.export_embeddings`; output is a full overwrite snapshot (not incremental)
and is gitignored (`data/`) since it scales with corpus size (~4-4.5
KB/vector).

## Migration trigger (documented, not yet needed)

Switch `vec_image` from sqlite-vec to **LanceDB** (embedded, file-based, native
IVF/HNSW) **only if** image-vector count materially exceeds ~1M *or* p95 query
latency becomes unacceptable. The `VectorStore` interface makes this a localized
change — the relational layer, FTS, and `vec_text` are unaffected.

## Web UI read path (`web/`)

A separate session built the read-only search UI/API in `web/` (FastAPI +
vanilla JS in `web/static/`), against `furniture.db` opened read-only
(`file:...?mode=ro`) and reusing `db.embeddings.provider.GeminiEmbeddingProvider`
/ `db.embeddings.store.SqliteVecStore` at query time (no `db/` edits). Status,
for awareness:

- `web/search.py`'s `SearchService.search_text` / `search_image` run FTS5 +
  `vec_text` + `vec_image`, fused with RRF, and are now **symmetric
  cross-modal**: a text query also ranks via `vec_image`, an image query also
  ranks via `vec_text` (shared `_image_hits_to_products` helper).
- `cosine_similarity(distance) = 1 - distance**2/2`, derived from sqlite-vec's
  **L2** distance (confirmed empirically via `vec_distance_l2`/
  `vec_distance_cosine` — sqlite-vec returns true Euclidean distance, not
  squared) for the unit-norm vectors `embedding_meta.normalized=1` guarantees.
- The UI shows this similarity as a % on result cards, a min-similarity
  threshold slider, and graph edge labels — all read from this single
  `cosine_similarity()` function, so the rescaling option below (Open items)
  would be a one-point change.

## Open items
- **Embedding `task_type` not set — similarity scores have a high floor.**
  `db/embeddings/provider.py`'s `_embed_chunk` calls
  `EmbedContentConfig(output_dimensionality=768)` with no `task_type`, for
  both ingestion (`vec_text`/`vec_image`) and query-time embedding
  (`web/search.py`). Measured effect: cosine similarity between *unrelated*
  texts (e.g. "rug" vs "stainless steel fork") is ~55-56%, so the
  discriminative range is roughly 50-90% rather than 0-100%. Also, the full
  `vec_text` doc (name + description + specs) scores lower against a short
  query (~50%) than the product name alone (~69%) — dilution from extra
  content. Two fixes considered, **neither started** (deferred):
  - (a) Set `task_type=RETRIEVAL_DOCUMENT` at ingest (`db/embed.py` →
    `vec_text`/`vec_image`) and `task_type=RETRIEVAL_QUERY` at query time
    (`web/search.py`) — the asymmetric mode Gemini recommends for retrieval.
    Requires a full re-embed of both vector tables, tracked via
    `embedding_meta` per the idempotent-re-embed contract above.
  - (b) Cosmetic only: rescale the displayed similarity % with an empirical
    floor/ceiling (e.g. ~50%→0%, ~90%→100%) inside `web/search.py`'s
    `cosine_similarity()`. No re-embed, doesn't change ranking, just the
    displayed number.
- Build out the canonical attribute vocabulary (`name_canonical` mapping) — the
  hardest cross-site normalization work, done incrementally.
- Decide RRF `k` and per-retriever weighting after first real queries.
