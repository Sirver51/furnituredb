-- Canonical data + FTS + vector schema. See docs/db_strategy.md for rationale.
-- Applied once at connection time (CREATE ... IF NOT EXISTS everywhere).

-- ── canonical buyable item (variant-level) ────────────────────────────────
CREATE TABLE IF NOT EXISTS product (
  id              INTEGER PRIMARY KEY,
  site            TEXT    NOT NULL,        -- 'panhome' | 'homecentre' | 'homesrus'
  source_id       TEXT    NOT NULL,        -- dedupe key: panhome int id / HC variant sku / HRU sku
  source_key      TEXT    NOT NULL,        -- raw filename stem
  group_key       TEXT,                    -- parent/configurable id; NULL if standalone
  is_group_parent INTEGER NOT NULL DEFAULT 0,
  sku             TEXT,
  name            TEXT    NOT NULL,
  description     TEXT,
  brand           TEXT,
  url             TEXT,
  currency        TEXT    DEFAULT 'AED',
  price           REAL,
  regular_price   REAL,
  discount_pct    REAL,
  availability    TEXT,
  rating_value    REAL,
  rating_count    INTEGER,
  taxonomy_path   TEXT,
  raw_path        TEXT    NOT NULL,
  content_hash    TEXT    NOT NULL,
  crawled_at      TEXT,
  ingested_at     TEXT,
  UNIQUE (site, source_id)
);
CREATE INDEX IF NOT EXISTS idx_product_group ON product(site, group_key);
CREATE INDEX IF NOT EXISTS idx_product_price ON product(price);

-- ── images (per-image; visual search keys off these) ──────────────────────
CREATE TABLE IF NOT EXISTS image (
  id           INTEGER PRIMARY KEY,
  product_id   INTEGER NOT NULL REFERENCES product(id),
  url          TEXT    NOT NULL,
  local_path   TEXT,
  position     INTEGER,
  is_primary   INTEGER NOT NULL DEFAULT 0,
  color_tag    TEXT,
  content_hash TEXT,
  UNIQUE (product_id, url)
);
CREATE INDEX IF NOT EXISTS idx_image_product ON image(product_id);

-- ── attributes (EAV: keep raw AND canonical) ──────────────────────────────
CREATE TABLE IF NOT EXISTS attribute (
  id              INTEGER PRIMARY KEY,
  product_id      INTEGER NOT NULL REFERENCES product(id),
  name_raw        TEXT NOT NULL,
  name_canonical  TEXT,
  value_raw       TEXT,
  value_canonical TEXT,
  unit            TEXT
);
CREATE INDEX IF NOT EXISTS idx_attr_product ON attribute(product_id);
CREATE INDEX IF NOT EXISTS idx_attr_canon   ON attribute(name_canonical, value_canonical);

-- ── lexical search ────────────────────────────────────────────────────────
-- Standalone (not external-content): `specs` is a derived/flattened field
-- with no matching `product` column, and managing rowid<->product.id by hand
-- is simplest this way. rowid is set explicitly to product.id on insert.
CREATE VIRTUAL TABLE IF NOT EXISTS product_fts USING fts5(name, description, specs);

-- ── vectors (sqlite-vec). Same Gemini space; separate tables by key grain. ──
CREATE VIRTUAL TABLE IF NOT EXISTS vec_text  USING vec0(product_id INTEGER PRIMARY KEY, embedding FLOAT[768]);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_image USING vec0(image_id   INTEGER PRIMARY KEY, embedding FLOAT[768]);

-- ── embedding provenance (gates full re-embeds on model change) ───────────
CREATE TABLE IF NOT EXISTS embedding_meta (
  modality   TEXT NOT NULL,               -- 'text' | 'image'
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  normalized INTEGER NOT NULL DEFAULT 1,
  created_at TEXT,
  PRIMARY KEY (modality, model)
);

-- ── embedding gate: content hash of the input last embedded for this ref ──
-- ref_id is product.id for kind='text', image.id for kind='image'. Re-embed
-- only when the current hash differs from what's stored here.
CREATE TABLE IF NOT EXISTS embedding_state (
  kind         TEXT    NOT NULL,          -- 'text' | 'image'
  ref_id       INTEGER NOT NULL,
  content_hash TEXT    NOT NULL,
  PRIMARY KEY (kind, ref_id)
);
