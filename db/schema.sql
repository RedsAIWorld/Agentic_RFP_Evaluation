-- Agentic RFP Evaluation — SQLite schema
-- Extends the brief's minimum design (Section 6) with fields required for
-- reproducibility, deterministic scoring, and auditability.

CREATE TABLE IF NOT EXISTS evaluation_criteria (
    criterion_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    weight          REAL NOT NULL,          -- percentage points, e.g. 30 for 30%
    max_score       INTEGER NOT NULL DEFAULT 10,
    scoring_source  TEXT NOT NULL DEFAULT 'llm'   -- 'llm' or 'deterministic'
                        CHECK (scoring_source IN ('llm', 'deterministic')),
    is_active       INTEGER NOT NULL DEFAULT 1,   -- 0/1 boolean
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rfp_runs (
    rfp_run_id            TEXT PRIMARY KEY,      -- UUID
    created_at            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'IN_PROGRESS'
                              CHECK (status IN ('IN_PROGRESS','INCOMPLETE','COMPLETE','FAILED')),
    criteria_snapshot_json TEXT NOT NULL,         -- frozen copy of active criteria used for this run
    provider              TEXT,                   -- e.g. "anthropic" (never the API key)
    model                 TEXT,                   -- e.g. "claude-sonnet-4-5-20250929"
    weight_warning        TEXT                    -- non-null if weights had to be normalized
);

CREATE TABLE IF NOT EXISTS supplier_results (
    supplier_result_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    rfp_run_id           TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id),
    supplier_name        TEXT NOT NULL,
    submission_date      TEXT NOT NULL,          -- ISO date, used in tie-break
    experience_rating    INTEGER NOT NULL,       -- 1-10, historical rating, TIE-BREAK ONLY
    is_incumbent          INTEGER NOT NULL DEFAULT 0,
    incumbent_performance_rating INTEGER,        -- 1-5, only meaningful if is_incumbent=1
    eval_status           TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (eval_status IN ('PENDING','SUCCESS','FAILED')),
    absolute_score        REAL,                  -- weighted % score, 0-100
    ppi                   REAL,                  -- Peer Performance Index, 0-100+
    final_rank            INTEGER,
    warnings_json         TEXT,                  -- list of validation/scoring warnings for this supplier
    result_json           TEXT,                  -- complete raw+validated+scored payload (source of truth)
    UNIQUE (rfp_run_id, supplier_name)
);
