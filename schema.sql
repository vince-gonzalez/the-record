-- ============================================================
-- THE RECORD - D1 schema v0.1.0
-- Append-only Modulign address ledger (spec 26.2 chain of custody).
-- F-Keys | www.f-keys.com
-- ============================================================
-- The chain rule: row_hash = sha256(prev_hash || canonical-row-json),
-- row 1 chains from sha256('THE-RECORD-GENESIS-2026'). Editing any row
-- breaks every hash after it. Rows are never UPDATEd or DELETEd; a
-- reclassification is a NEW row whose address supersedes by timestamp.

CREATE TABLE IF NOT EXISTS ledger (
  seq            INTEGER PRIMARY KEY,   -- append order, dense from 1
  gsi_id         TEXT NOT NULL UNIQUE,  -- UUIDv4, permanent (spec 22.1)
  mgn            TEXT NOT NULL,         -- canonical Modulign address
  doc_source     TEXT NOT NULL,         -- 'cap-static'
  doc_id         TEXT NOT NULL,         -- source-system id
  doc_url        TEXT NOT NULL,         -- canonical public artifact URL
  doc_sha256     TEXT NOT NULL,         -- sha256 of the exact bytes fetched
  doc_title      TEXT,
  doc_cite       TEXT,                  -- official citation when present
  doc_date       TEXT,                  -- the document's own date
  court          TEXT,
  jurisdiction   TEXT NOT NULL,         -- CAP jurisdiction name_long
  classified_at  TEXT NOT NULL,         -- ISO 8601 UTC, the record clock
  spec_version   TEXT NOT NULL,         -- 'Modulign Standard v3.0'
  spec_sha256    TEXT NOT NULL,         -- hash of the spec PDF (spec 26.3)
  classifier     TEXT NOT NULL,         -- addresser version string
  prev_hash      TEXT NOT NULL,
  row_hash       TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_ledger_jur  ON ledger (jurisdiction);
CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger (classified_at);

-- Chain-head anchors: periodically published outside this database
-- (a git commit, a deposit) so the chain verifies against a copy the
-- database operator cannot rewrite.
CREATE TABLE IF NOT EXISTS anchors (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  through_seq  INTEGER NOT NULL,
  chain_head   TEXT NOT NULL,
  anchored_at  TEXT NOT NULL,
  anchor_kind  TEXT NOT NULL,           -- 'git-commit' | 'zenodo' | ...
  anchor_ref   TEXT NOT NULL            -- commit hash, DOI, URL
);
