CREATE TABLE IF NOT EXISTS execution_traces (
    trace_id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    terminal_reason TEXT,
    regime TEXT,
    confidence REAL,
    adx REAL,
    gate_score REAL,
    ecel_decision TEXT,
    slippage_bps REAL,
    fill_latency_ms REAL,
    quality_grade CHAR(1),
    trace_path TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    filled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS trace_stage_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_traces_pair_created ON execution_traces(pair, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_traces_regime ON execution_traces(regime);
CREATE INDEX IF NOT EXISTS idx_execution_traces_status ON execution_traces(status);
CREATE INDEX IF NOT EXISTS idx_trace_stage_events_trace_id_ts ON trace_stage_events(trace_id, ts);
