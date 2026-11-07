-- 002: every backtest run is recorded (multiple-testing counter; holdout usage is visible)
CREATE TABLE backtest_runs (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy    TEXT  NOT NULL,
    version     TEXT,
    params      JSONB NOT NULL DEFAULT '{}'::jsonb,
    period      TEXT  NOT NULL CHECK (period IN ('train','validate','holdout','custom')),
    start_date  DATE  NOT NULL,
    end_date    DATE  NOT NULL,
    metrics     JSONB NOT NULL,
    notes       TEXT
);
CREATE INDEX backtest_runs_strategy_idx ON backtest_runs (strategy, created_at DESC);
