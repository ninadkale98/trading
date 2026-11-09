-- 016: the earnings release reader (build plan 4.1, core/jobs/earnings_reads.py).
-- One row per 8-K item 2.02 filing whose press release (exhibit 99.1) Claude has read. Company names, tickers, web
-- addresses and calendar years are masked before reading, so live and history reads see the same kind of text.
-- mode: 'live' = read within 3 days of the filing (no hindsight possible); 'history' = read later (backfill: the model
-- may still recognise a company from its numbers, so history reads are research material and forward tests decide).
CREATE TABLE IF NOT EXISTS earnings_reads (
    accession        TEXT PRIMARY KEY,
    symbol           TEXT NOT NULL,
    cik              BIGINT NOT NULL,
    accepted_at      TIMESTAMPTZ,
    filed_at         DATE NOT NULL,
    mode             TEXT NOT NULL CHECK (mode IN ('live', 'history')),
    model            TEXT,
    status           TEXT NOT NULL CHECK (status IN ('ok', 'not_results', 'no_release', 'error')),
    doc_url          TEXT,
    chars            INT,
    fiscal_period    TEXT,
    currency         TEXT,
    revenue_musd     DOUBLE PRECISION,       -- quarter's total revenue, millions (in `currency`)
    revenue_yoy      REAL,                   -- fraction, as stated in the release
    eps_gaap         REAL,
    eps_adj          REAL,
    guidance         TEXT,                   -- raised | maintained | lowered | initiated | withdrawn | mixed | none
    guidance_detail  TEXT,
    tone             SMALLINT,               -- −2 … +2
    one_offs         TEXT,
    positives        JSONB,
    negatives        JSONB,
    eps_estimate     REAL,                   -- consensus known before the release (earnings_calendar snapshot)
    revenue_estimate DOUBLE PRECISION,       -- USD
    eps_surprise     REAL,                   -- (adjusted EPS − estimate) / |estimate|
    rev_surprise     REAL,                   -- (revenue − estimate) / estimate, USD reporters only
    raw              JSONB,
    error            TEXT,
    read_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS earnings_reads_symbol ON earnings_reads (symbol, accepted_at);

ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS release_tone REAL;
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS guidance_change SMALLINT;
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS rev_surprise REAL;

GRANT SELECT ON earnings_reads TO tradebot_ro;
