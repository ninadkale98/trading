-- 011: daily strategy candidates, trade plans, our position book, approvals (architecture §10–11, build plan 2.4–2.6).

CREATE TABLE strategy_candidates (
    date        DATE NOT NULL,            -- signal day (data through its close)
    strategy    TEXT NOT NULL,
    stage       TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    score       REAL,
    close       REAL,
    stop        REAL NOT NULL,
    target      REAL,
    trail_pct   REAL,
    max_hold    INT,
    rationale   TEXT,
    facts       JSONB,
    PRIMARY KEY (date, strategy, symbol)
);

CREATE TABLE trade_plans (
    id              BIGSERIAL PRIMARY KEY,
    signal_date     DATE NOT NULL,
    trade_date      DATE NOT NULL,        -- the session the order is for
    mode            TEXT NOT NULL CHECK (mode IN ('dry_run', 'paper')),
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL DEFAULT 'buy' CHECK (side IN ('buy', 'sell')),
    shares          INT  NOT NULL,
    limit_price     REAL,
    stop            REAL,
    target          REAL,
    trail_pct       REAL,
    max_hold        INT,
    risk_dollars    REAL,
    risk_pct        REAL,
    position_value  REAL,
    reason          TEXT,                 -- why planned (or why it's an exit)
    needs_approval  BOOLEAN NOT NULL DEFAULT false,
    status          TEXT NOT NULL DEFAULT 'planned'
                    CHECK (status IN ('planned', 'waiting_approval', 'rejected', 'submitted', 'filled', 'partially_filled',
                                      'cancelled', 'expired', 'error', 'simulated')),
    broker_order_id TEXT,
    fill_price      REAL,
    filled_shares   INT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (trade_date, strategy, symbol, side, mode)
);
CREATE INDEX trade_plans_status_idx ON trade_plans (status, trade_date);

-- Our own record of each position: which strategy owns it, its stop/target/trailing/time rules (Alpaca only knows orders).
CREATE TABLE positions_book (
    id            BIGSERIAL PRIMARY KEY,
    mode          TEXT NOT NULL CHECK (mode IN ('dry_run', 'paper')),
    plan_id       BIGINT REFERENCES trade_plans (id),
    strategy      TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    shares        INT  NOT NULL,
    entry_date    DATE NOT NULL,
    entry_price   REAL NOT NULL,
    stop          REAL NOT NULL,
    target        REAL,
    trail_pct     REAL,
    high_close    REAL,
    max_hold      INT,
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    exit_date     DATE,
    exit_price    REAL,
    exit_reason   TEXT,
    pnl           REAL,
    spy_entry     REAL,                    -- SPY close at entry, to score the trade against SPY
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX positions_book_open_idx ON positions_book (mode, symbol) WHERE status = 'open';

CREATE TABLE approvals (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,             -- emerging_stock | conviction | hold_through_earnings | first_trades | circuit_breaker
    plan_id     BIGINT REFERENCES trade_plans (id),
    title       TEXT NOT NULL,
    case_for    TEXT,
    case_against TEXT,
    details     JSONB,
    deadline    TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    size_factor REAL,                      -- "approve, half size" → 0.5
    comment     TEXT,
    decided_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX approvals_status_idx ON approvals (status, deadline);
