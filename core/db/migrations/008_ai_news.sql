-- 008: Claude usage log, and what Haiku understood from each news item.

CREATE TABLE ai_usage (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    task_id        BIGINT,
    purpose        TEXT NOT NULL,                 -- e.g. 'news.triage'
    model          TEXT NOT NULL,                 -- haiku | sonnet | opus
    ok             BOOLEAN NOT NULL,
    input_tokens   INT, output_tokens INT, cache_read_tokens INT, cache_write_tokens INT,
    cost_usd_equiv REAL,                          -- what the same call would cost on the pay-per-use API (a usage meter)
    duration_ms    INT,
    error          TEXT
);
CREATE INDEX ai_usage_ts_idx ON ai_usage (ts DESC);

-- Each news item read by the AI (also marks it processed, even if nothing relevant was found).
CREATE TABLE news_ai (
    news_id      BIGINT PRIMARY KEY REFERENCES news (id) ON DELETE CASCADE,
    model        TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recap        BOOLEAN,                         -- only describes a price move, no new information
    topic        TEXT                             -- for news without a company: macro_policy, sector_industry, market_recap …
);

-- One row per (news item, company it really affects).
CREATE TABLE news_events (
    news_id     BIGINT NOT NULL REFERENCES news (id) ON DELETE CASCADE,
    symbol      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    direction   SMALLINT NOT NULL CHECK (direction BETWEEN -2 AND 2),   -- −2 very negative … +2 very positive
    importance  SMALLINT NOT NULL CHECK (importance BETWEEN 1 AND 5),   -- how much it could change the company's value
    created_at  TIMESTAMPTZ NOT NULL,             -- copied from the news item (point-in-time)
    PRIMARY KEY (news_id, symbol)
);
CREATE INDEX news_events_symbol_idx ON news_events (symbol, created_at DESC);
CREATE INDEX news_events_created_idx ON news_events (created_at DESC);
