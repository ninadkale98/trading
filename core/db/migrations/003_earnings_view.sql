-- 003: past earnings releases, from 8-K item 2.02 ("Results of Operations and Financial Condition").
-- timing: filed at/after 4 pm ET → the market reacts the NEXT trading day; before 9:30 am → same day.
CREATE OR REPLACE VIEW earnings_events AS
SELECT s.symbol,
       f.cik,
       f.accession,
       f.filed_at,
       f.accepted_at,
       CASE
         WHEN f.accepted_at IS NULL THEN 'unknown'
         WHEN (f.accepted_at AT TIME ZONE 'America/New_York')::time >= TIME '16:00' THEN 'after_close'
         WHEN (f.accepted_at AT TIME ZONE 'America/New_York')::time <  TIME '09:30' THEN 'before_open'
         ELSE 'during_market'
       END AS timing
FROM filings f
JOIN (SELECT DISTINCT ON (cik) cik, symbol FROM stocks WHERE is_universe AND cik IS NOT NULL ORDER BY cik, symbol) s
  ON s.cik = f.cik
WHERE f.form IN ('8-K', '8-K/A') AND f.items LIKE '%2.02%';
