-- TIQ v515 test-only durable ledger. Apply only to an independently isolated
-- sandbox PostgreSQL database after backup and migration review.
-- Do not run against production billing, course sandbox or Kraken databases.
BEGIN;
CREATE TABLE IF NOT EXISTS tiq72_v515_runs (
  run_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  canonical_run JSONB NOT NULL,
  version TEXT NOT NULL DEFAULT 'v515-72-decisions',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tiq72_v515_run_version CHECK (version = 'v515-72-decisions'),
  CONSTRAINT tiq72_v515_owner_nonempty CHECK (length(owner_id) BETWEEN 1 AND 160)
);
CREATE TABLE IF NOT EXISTS tiq72_v515_reservations (
  reservation_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES tiq72_v515_runs(run_id),
  owner_id TEXT NOT NULL,
  stripe_session TEXT UNIQUE,
  state TEXT NOT NULL DEFAULT 'reserved',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tiq72_v515_state CHECK (state IN
    ('reserved', 'checkout_created', 'paid', 'refunded', 'disputed')),
  CONSTRAINT tiq72_v515_owner_nonempty CHECK (length(owner_id) BETWEEN 1 AND 160),
  CONSTRAINT tiq72_v515_session_test_only CHECK
    (stripe_session IS NULL OR stripe_session LIKE 'cs_test_%')
);
CREATE INDEX IF NOT EXISTS tiq72_v515_res_owner_run
  ON tiq72_v515_reservations (owner_id, run_id);
CREATE TABLE IF NOT EXISTS tiq72_v515_reports (
  run_id TEXT PRIMARY KEY REFERENCES tiq72_v515_runs(run_id),
  reservation_id TEXT NOT NULL UNIQUE REFERENCES tiq72_v515_reservations(reservation_id),
  owner_id TEXT NOT NULL,
  stripe_session TEXT NOT NULL UNIQUE,
  report JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Never delete refunded/disputed reservations; their state revokes access
-- even if a historical report is retained for accounting.
COMMIT;
