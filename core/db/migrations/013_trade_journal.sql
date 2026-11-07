-- 013: what we need to LEARN from every trade (dry run and paper alike).
--   entry_context: the stock's features on the signal day, the market regime, the strategy's reason, recent news
--   mfe / mae: best and worst point while open (max favourable / adverse excursion, as % from entry)
--   exit_context: the stock's features and the market on the exit day; spy_exit for the vs-SPY score
ALTER TABLE positions_book ADD COLUMN entry_context JSONB;
ALTER TABLE positions_book ADD COLUMN exit_context JSONB;
ALTER TABLE positions_book ADD COLUMN mfe REAL;
ALTER TABLE positions_book ADD COLUMN mae REAL;
ALTER TABLE positions_book ADD COLUMN spy_exit REAL;

-- Weekly AI review of trades and the lessons drawn (feeds the idea lab).
CREATE TABLE trade_reviews (
    week_start   DATE PRIMARY KEY,
    model        TEXT NOT NULL,
    review_md    TEXT NOT NULL,
    lessons      JSONB,                        -- [{lesson, evidence, suggested_test}]
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
