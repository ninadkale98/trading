-- Idea lab: the self-improving loop (architecture §9, build plan Phase 4).
-- Every idea is recorded BEFORE it's tested (hypothesis first), with its code, test results, verdict and lesson.
CREATE TABLE IF NOT EXISTS ideas (
    id            bigserial PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    round_id      bigint,
    source        text NOT NULL DEFAULT 'opus',        -- opus | user | big_moves | ...
    name          text NOT NULL UNIQUE,                -- strategy name (snake_case), also the file name
    title         text NOT NULL,
    kind          text NOT NULL DEFAULT 'new',         -- new | variant
    parent        text,                                -- strategy it varies, if any
    hypothesis    text NOT NULL,                       -- why it might work, written before testing
    rules         text NOT NULL,                       -- plain-language rules handed to the builder
    status        text NOT NULL DEFAULT 'proposed',    -- proposed | built | build_failed | tested | live | rejected | promoted | retired
    code_path     text,
    build_attempts int NOT NULL DEFAULT 0,
    build_error   text,
    results       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- lookahead check, signal study, train backtest gates
    verdict       text,
    lesson        text,
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ideas_status ON ideas (status);

CREATE TABLE IF NOT EXISTS lab_rounds (
    id           bigserial PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    proposal_md  text,                                 -- Opus: what it looked at and why these ideas
    report_md    text,                                 -- Opus: what the round found
    feature_requests jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary      jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Stage changes of any strategy (admitted, retired, promoted), with the reason: the lab's audit trail.
CREATE TABLE IF NOT EXISTS strategy_moves (
    id         bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    strategy   text NOT NULL,
    from_stage text,
    to_stage   text NOT NULL,
    reason     text NOT NULL,
    evidence   jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Weekly "engineer" runs: Claude Code improving the system itself on a git branch.
CREATE TABLE IF NOT EXISTS engineer_runs (
    id           bigserial PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    branch       text NOT NULL,
    status       text NOT NULL DEFAULT 'running',      -- running | merged | needs_review | no_change | failed
    goal         text,
    summary_md   text,
    files        jsonb NOT NULL DEFAULT '[]'::jsonb,
    checks       jsonb NOT NULL DEFAULT '{}'::jsonb,
    commit_sha   text
);
