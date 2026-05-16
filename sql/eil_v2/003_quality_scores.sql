CREATE TABLE IF NOT EXISTS quality_scores (
    trace_id TEXT PRIMARY KEY REFERENCES execution_traces(trace_id) ON DELETE CASCADE,
    pass_probability REAL,
    expected_grade CHAR(1),
    slippage_risk_score REAL,
    regime_alignment_score REAL,
    path_seen_before BOOLEAN NOT NULL DEFAULT FALSE,
    similar_path_win_rate REAL,
    confidence_interval REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_scores_created_at ON quality_scores(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_scores_expected_grade ON quality_scores(expected_grade);
