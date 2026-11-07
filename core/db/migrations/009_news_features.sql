-- 009: per-stock news features from Haiku's labels (core/features/news.py).
ALTER TABLE features_daily ADD COLUMN news_count_5d SMALLINT;
ALTER TABLE features_daily ADD COLUMN news_score_5d REAL;
ALTER TABLE features_daily ADD COLUMN news_major_5d REAL;
