-- 001: system tables + core market data (docs/architecture.md §4, §14)

CREATE EXTENSION IF NOT EXISTS vector;

-- ───────────────────────────── SYSTEM ─────────────────────────────

CREATE TABLE tasks (
    id            BIGSERIAL PRIMARY KEY,
    type          TEXT        NOT NULL,
    payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    priority      INT         NOT NULL DEFAULT 50,          -- higher runs first
    status        TEXT        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','done','deferred','failed','expired','cancelled')),
    resource      TEXT,                                      -- e.g. 'alpaca', 'sec', 'claude:opus' (pausable)
    dedupe_key    TEXT,                                      -- same key can't be queued twice while open
    attempts      INT         NOT NULL DEFAULT 0,
    max_attempts  INT         NOT NULL DEFAULT 6,
    next_try_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,
    locked_by     TEXT,
    locked_at     TIMESTAMPTZ,
    progress      JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- checkpoint so retries resume
    result        JSONB,
    last_error    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE INDEX tasks_ready_idx ON tasks (status, next_try_at, priority DESC) WHERE status IN ('pending','deferred');
CREATE UNIQUE INDEX tasks_dedupe_open_idx ON tasks (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending','running','deferred');
CREATE INDEX tasks_created_idx ON tasks (created_at DESC);

-- A paused resource (e.g. a Claude model after a usage limit, or an API during an outage)
CREATE TABLE resource_pauses (
    resource     TEXT PRIMARY KEY,
    paused_until TIMESTAMPTZ NOT NULL,
    reason       TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Recurring jobs; the scheduler turns these into tasks
CREATE TABLE schedules (
    name            TEXT PRIMARY KEY,
    task_type       TEXT    NOT NULL,
    payload         JSONB   NOT NULL DEFAULT '{}'::jsonb,
    cron            TEXT    NOT NULL,             -- "m h dom mon dow" in America/New_York
    priority        INT     NOT NULL DEFAULT 50,
    resource        TEXT,
    expires_minutes INT,                          -- drop the task if it hasn't run within N minutes
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_fired_at   TIMESTAMPTZ
);

-- "Today" timeline and audit trail
CREATE TABLE events (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    level    TEXT        NOT NULL DEFAULT 'info' CHECK (level IN ('debug','info','warn','error')),
    kind     TEXT        NOT NULL,
    message  TEXT        NOT NULL,
    data     JSONB,
    task_id  BIGINT
);
CREATE INDEX events_ts_idx ON events (ts DESC);

CREATE TABLE errors (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    task_id    BIGINT,
    task_type  TEXT,
    error_type TEXT,
    message    TEXT,
    traceback  TEXT
);
CREATE INDEX errors_ts_idx ON errors (ts DESC);

CREATE TABLE heartbeats (
    component TEXT PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    info      JSONB
);

-- ─────────────────────────── MARKET DATA ───────────────────────────

-- Every listing Alpaca knows (active + delisted). Symbols can be reused by new companies over time.
CREATE TABLE stocks (
    alpaca_id       UUID PRIMARY KEY,
    symbol          TEXT        NOT NULL,
    name            TEXT,
    exchange        TEXT,
    status          TEXT,                       -- active / inactive
    tradable        BOOLEAN,
    asset_type      TEXT,                       -- common / etf / warrant / unit / right / preferred / other
    is_universe     BOOLEAN     NOT NULL DEFAULT false,   -- in our ~5,000 common-stock universe (or a reference ETF)
    cik             BIGINT,
    sic             INT,
    sic_description TEXT,
    sector          TEXT,
    attributes      JSONB,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    delisted_seen   TIMESTAMPTZ,                -- when we first saw it inactive
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX stocks_symbol_idx ON stocks (symbol);
CREATE INDEX stocks_universe_idx ON stocks (is_universe) WHERE is_universe;
CREATE INDEX stocks_cik_idx ON stocks (cik);

-- Daily bars. Raw prices + an adjustment factor (split & dividend): adjusted = raw × adj_factor.
CREATE TABLE daily_prices (
    symbol      TEXT        NOT NULL,
    date        DATE        NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT      NOT NULL,
    vwap        DOUBLE PRECISION,
    trade_count INT,
    adj_factor  DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    known_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX daily_prices_date_idx ON daily_prices (date);

-- Daily liquidity tier per stock (architecture §3)
CREATE TABLE liquidity (
    symbol         TEXT NOT NULL,
    date           DATE NOT NULL,
    price          DOUBLE PRECISION,
    adv20_dollar   DOUBLE PRECISION,   -- 20-day average dollar volume
    tier           TEXT CHECK (tier IN ('liquid','thin','emerging')),
    PRIMARY KEY (symbol, date)
);

CREATE TABLE news (
    id          BIGINT PRIMARY KEY,               -- Alpaca news id
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ,
    headline    TEXT NOT NULL,
    summary     TEXT,
    content     TEXT,                              -- only for stock-focused items (≤ 3 symbols)
    author      TEXT,
    source      TEXT,
    url         TEXT,
    symbols     TEXT[] NOT NULL DEFAULT '{}',
    n_symbols   INT GENERATED ALWAYS AS (cardinality(symbols)) STORED,
    known_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX news_created_idx ON news (created_at DESC);
CREATE INDEX news_symbols_idx ON news USING GIN (symbols);

-- SEC filings index
CREATE TABLE filings (
    accession    TEXT PRIMARY KEY,
    cik          BIGINT NOT NULL,
    form         TEXT   NOT NULL,
    filed_at     DATE   NOT NULL,
    accepted_at  TIMESTAMPTZ,
    report_date  DATE,
    items        TEXT,                              -- 8-K items, e.g. "2.02,9.01"
    primary_doc  TEXT,
    known_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX filings_cik_idx ON filings (cik, filed_at DESC);
CREATE INDEX filings_form_idx ON filings (form, filed_at DESC);

-- XBRL financial facts (point-in-time by filed date)
CREATE TABLE financials (
    id           BIGSERIAL PRIMARY KEY,
    cik          BIGINT NOT NULL,
    concept      TEXT   NOT NULL,                   -- e.g. Revenues, GrossProfit, NetIncomeLoss
    unit         TEXT   NOT NULL,
    period_start DATE,
    period_end   DATE   NOT NULL,
    fy           INT,
    fp           TEXT,                               -- Q1/Q2/Q3/FY
    form         TEXT,
    filed        DATE   NOT NULL,
    accession    TEXT   NOT NULL,
    value        DOUBLE PRECISION NOT NULL,
    known_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX financials_fact_uidx
    ON financials (cik, concept, unit, period_end, accession, (COALESCE(period_start, DATE '1900-01-01')));
CREATE INDEX financials_lookup_idx ON financials (cik, concept, period_end);

-- Insider trades (SEC Form 4)
CREATE TABLE insider_trades (
    accession      TEXT   NOT NULL,
    line           INT    NOT NULL,
    issuer_cik     BIGINT NOT NULL,
    symbol         TEXT,
    owner_name     TEXT,
    owner_role     TEXT,
    trade_date     DATE,
    code           TEXT,                             -- P = open-market buy, S = sale, ...
    shares         DOUBLE PRECISION,
    price          DOUBLE PRECISION,
    acquired       BOOLEAN,
    shares_after   DOUBLE PRECISION,
    filed_at       DATE   NOT NULL,
    known_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (accession, line)
);
CREATE INDEX insider_issuer_idx ON insider_trades (issuer_cik, trade_date DESC);
