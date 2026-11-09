-- Read-only login used by the weekly engineer (and future AI search tools) to explore data without being able to
-- change it: postgresql:///market?user=tradebot_ro
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradebot_ro') THEN CREATE ROLE tradebot_ro LOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO tradebot_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tradebot_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO tradebot_ro;
