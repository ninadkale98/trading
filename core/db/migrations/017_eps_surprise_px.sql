-- Price-scaled EPS surprise (SUE-style): (actual − estimate) ÷ close before the report. build-plan §4.1, 2026-11-10.
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS eps_surprise_px REAL;
-- Crash features (user idea 2026-11-09): lets the lab test big_crash_capitulation with stored daily features.
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS dist_60d_high REAL;
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS heavy_sell_age SMALLINT;
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS adv_rank SMALLINT;
ALTER TABLE features_daily ADD COLUMN IF NOT EXISTS big_steady_250 REAL;
