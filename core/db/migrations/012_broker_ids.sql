-- 012: broker order ids on positions (the protective stop leg we raise for trailing stops).
ALTER TABLE positions_book ADD COLUMN stop_order_id TEXT;
ALTER TABLE positions_book ADD COLUMN broker_stop REAL;
