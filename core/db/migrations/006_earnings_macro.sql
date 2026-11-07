-- 006: earnings calendar + estimates (point-in-time snapshots), earnings history, analyst rating counts,
-- macro data (first-published values), and an API usage counter for daily-capped services.

CREATE TABLE api_usage (
    source      TEXT NOT NULL,
    day         DATE NOT NULL,
    n           INT  NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, day)
);

-- One row per (source, snapshot day, company, fiscal period): what the calendar said on that day.
-- Keeping every day's snapshot builds our own history of estimates and date changes from now on.
CREATE TABLE earnings_calendar (
    source            TEXT NOT NULL,          -- 'alphavantage' | 'finnhub'
    as_of             DATE NOT NULL,
    symbol            TEXT NOT NULL,
    report_date       DATE NOT NULL,
    fiscal_period_end DATE,
    fiscal_label      TEXT,                   -- e.g. '2026Q3' when the source gives year/quarter instead of a date
    eps_estimate      REAL,
    revenue_estimate  DOUBLE PRECISION,
    time_of_day       TEXT,                   -- 'before_open' | 'after_close' | 'during_market' | NULL
    known_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, as_of, symbol, report_date)
);
CREATE INDEX earnings_calendar_symbol_idx ON earnings_calendar (symbol, report_date);
CREATE INDEX earnings_calendar_asof_idx ON earnings_calendar (as_of);

-- Latest view of upcoming reports: per symbol, the next date from the most recent snapshot of each source.
CREATE VIEW upcoming_earnings AS
WITH latest AS (SELECT source, max(as_of) d FROM earnings_calendar GROUP BY source)
SELECT e.symbol, min(e.report_date) AS report_date,
       array_agg(DISTINCT e.source) AS sources,
       max(e.eps_estimate) FILTER (WHERE e.source = 'finnhub')      AS eps_estimate_finnhub,
       max(e.eps_estimate) FILTER (WHERE e.source = 'alphavantage') AS eps_estimate_alphavantage,
       max(e.time_of_day) AS time_of_day
FROM earnings_calendar e JOIN latest l ON l.source = e.source AND l.d = e.as_of
WHERE e.report_date >= current_date
GROUP BY e.symbol;

CREATE TABLE earnings_history (
    source            TEXT NOT NULL,          -- 'alphavantage'
    symbol            TEXT NOT NULL,
    fiscal_period_end DATE NOT NULL,
    reported_date     DATE,
    report_time       TEXT,                   -- 'before_open' | 'after_close'
    reported_eps      REAL,
    estimated_eps     REAL,
    surprise          REAL,
    surprise_pct      REAL,
    known_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, symbol, fiscal_period_end)
);
CREATE INDEX earnings_history_reported_idx ON earnings_history (symbol, reported_date);

CREATE TABLE analyst_ratings (               -- Finnhub monthly counts of analyst opinions
    symbol       TEXT NOT NULL,
    period       DATE NOT NULL,
    strong_buy   INT, buy INT, hold INT, sell INT, strong_sell INT,
    known_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, period)
);

CREATE TABLE macro_series (
    series_id    TEXT PRIMARY KEY,
    title        TEXT,
    frequency    TEXT,
    units        TEXT,
    grp          TEXT,                       -- rates, credit, inflation, jobs, growth, housing, dollar_oil, conditions
    last_loaded  TIMESTAMPTZ
);

-- value_first = the number as first published, first_known = the day it was published (point-in-time);
-- value_latest = today's (possibly revised) number.
CREATE TABLE macro_obs (
    series_id    TEXT NOT NULL REFERENCES macro_series (series_id),
    date         DATE NOT NULL,
    value_first  DOUBLE PRECISION,
    first_known  DATE,
    value_latest DOUBLE PRECISION,
    PRIMARY KEY (series_id, date)
);
