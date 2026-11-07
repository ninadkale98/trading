-- 007: company fundamentals in the daily features (point-in-time from SEC filings; core/features/fundamentals.py).
ALTER TABLE features_daily ADD COLUMN market_cap DOUBLE PRECISION;
ALTER TABLE features_daily ADD COLUMN revenue_ttm DOUBLE PRECISION;
ALTER TABLE features_daily ADD COLUMN rev_growth_yoy REAL;
ALTER TABLE features_daily ADD COLUMN rev_growth_q REAL;
ALTER TABLE features_daily ADD COLUMN gross_margin REAL;
ALTER TABLE features_daily ADD COLUMN op_margin REAL;
ALTER TABLE features_daily ADD COLUMN op_margin_chg REAL;
ALTER TABLE features_daily ADD COLUMN net_margin REAL;
ALTER TABLE features_daily ADD COLUMN pe REAL;
ALTER TABLE features_daily ADD COLUMN ps REAL;
ALTER TABLE features_daily ADD COLUMN fcf_yield REAL;
ALTER TABLE features_daily ADD COLUMN roe REAL;
ALTER TABLE features_daily ADD COLUMN debt_to_equity REAL;
ALTER TABLE features_daily ADD COLUMN insider_buyers_90d SMALLINT;
ALTER TABLE features_daily ADD COLUMN insider_net_buy_90d REAL;
ALTER TABLE features_daily ADD COLUMN eps_surprise REAL;
