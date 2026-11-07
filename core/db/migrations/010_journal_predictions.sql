-- 010: the market journal (one AI-written analysis per day) and the predictions log (architecture §5.5).

CREATE TABLE market_journal (
    date         DATE PRIMARY KEY,               -- the trading day analysed
    model        TEXT NOT NULL,
    summary      TEXT NOT NULL,                  -- ~5 lines: what the day meant
    analysis_md  TEXT NOT NULL,                  -- the full write-up (also saved to reports/market/)
    lesson       JSONB,                          -- {term, explanation}
    watch        JSONB,                          -- things to watch next
    pack_chars   INT,                            -- size of the market pack it read
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every forecast, in a form Python can check. kind:
--   'outperform'  symbol beats benchmark over horizon_days (direction 'up') or lags it ('down')
--   'move'        symbol's own return over horizon_days is > +threshold ('up') or < −threshold ('down')
CREATE TABLE predictions (
    id            BIGSERIAL PRIMARY KEY,
    made_on       DATE NOT NULL,                 -- trading day of the information used
    source        TEXT NOT NULL,                 -- e.g. 'opus.market_analysis'
    kind          TEXT NOT NULL CHECK (kind IN ('outperform', 'move')),
    symbol        TEXT NOT NULL,
    benchmark     TEXT,
    direction     TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    threshold     REAL NOT NULL DEFAULT 0,
    horizon_days  INT  NOT NULL CHECK (horizon_days BETWEEN 1 AND 260),
    probability   REAL NOT NULL CHECK (probability > 0 AND probability < 1),
    statement     TEXT NOT NULL,                 -- plain-language version
    reasoning     TEXT,
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'right', 'wrong', 'void')),
    start_price   DOUBLE PRECISION,              -- symbol close on made_on (adjusted)
    start_bench   DOUBLE PRECISION,
    outcome       REAL,                          -- realised return (or excess return for 'outperform')
    resolved_on   DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX predictions_open_idx ON predictions (status, made_on);
