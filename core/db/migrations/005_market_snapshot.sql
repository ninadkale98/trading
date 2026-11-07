-- 005: one market snapshot per trading day (architecture §5.6): breadth, rotation, style, cross-asset, global,
-- leaders, regime label and exposure-dial level. `data` holds the full snapshot (see core/market/snapshot.py).
CREATE TABLE market_snapshot (
    date         DATE PRIMARY KEY,
    regime       TEXT NOT NULL,
    exposure     REAL NOT NULL,          -- suggested invested share for the exposure dial (0–1)
    data         JSONB NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
