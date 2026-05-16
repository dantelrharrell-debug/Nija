CREATE TABLE IF NOT EXISTS failure_clusters (
    cluster_id TEXT PRIMARY KEY,
    trace_path TEXT[] NOT NULL DEFAULT '{}',
    regime TEXT NOT NULL,
    sample_count INT NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    rejection_rate REAL NOT NULL DEFAULT 0,
    centroid_confidence REAL NOT NULL DEFAULT 0,
    centroid_adx REAL NOT NULL DEFAULT 0,
    label TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_failure_clusters_regime ON failure_clusters(regime);
CREATE INDEX IF NOT EXISTS idx_failure_clusters_last_seen ON failure_clusters(last_seen DESC);
