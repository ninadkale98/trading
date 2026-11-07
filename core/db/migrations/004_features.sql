-- 004: daily features for every stock (architecture §7). Computed by core/features (the same code the backtester uses).
-- Stored for recent years only (settings: features.store_from); older dates are recomputed on demand.
-- Column meanings: core/features/price.py FEATURES and core/features/earnings.py FEATURES.
CREATE TABLE features_daily (
    symbol                 TEXT NOT NULL,
    date                   DATE NOT NULL,
    close                  REAL,
    ret_1d                 REAL,
    ret_5d                 REAL,
    ret_20d                REAL,
    ret_60d                REAL,
    ret_120d               REAL,
    ret_250d               REAL,
    dist_sma20             REAL,
    dist_sma50             REAL,
    dist_sma200            REAL,
    sma50_slope            REAL,
    sma200_slope           REAL,
    rsi14                  REAL,
    atr_pct                REAL,
    vol20                  REAL,
    vol60                  REAL,
    rvol                   REAL,
    adv20                  DOUBLE PRECISION,
    accum_20               REAL,
    accum_50               REAL,
    dist_52w_high          REAL,
    dist_52w_low           REAL,
    gap                    REAL,
    rs_spy_60              REAL,
    rs_spy_120             REAL,
    rs_sector_60           REAL,
    rs_rank                SMALLINT,
    beta_250               REAL,
    trend_score            SMALLINT,
    days_since_earnings    SMALLINT,
    earnings_reaction      REAL,
    days_to_earnings_est   SMALLINT,
    extra                  JSONB,                 -- room for experimental features before they get a column
    computed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, date)
);
CREATE INDEX features_daily_date_idx ON features_daily (date);
