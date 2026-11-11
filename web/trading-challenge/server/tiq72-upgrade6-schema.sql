-- NIJA Trading IQ v515 Upgrade 6: isolated TEST database schema.
-- REVIEW ONLY. Not executed. No shared application or trading tables.
-- Apply only after backup and restore procedure are verified.
BEGIN;
CREATE TABLE IF NOT EXISTS tiq_runs (
 id text PRIMARY KEY CHECK (id ~ '^run_[0-9a-f]{32}$'),
 owner_hash text NOT NULL CHECK (owner_hash ~ '^[0-9a-f]{64}$'),
 game_version text NOT NULL,
 mode text NOT NULL CHECK (mode IN ('standard','daily')),
 level text NOT NULL CHECK (level IN ('beginner','intermediate','advanced')),
 decisions_json jsonb NOT NULL,
 score_json jsonb NOT NULL,
 run_digest text NOT NULL CHECK (run_digest ~ '^[0-9a-f]{64}$'),
 adult_attested_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS tiq_checkouts (
 id uuid PRIMARY KEY,
 run_id text NOT NULL REFERENCES tiq_runs(id),
 stripe_session_id text UNIQUE,
 stripe_idempotency_key text NOT NULL UNIQUE,
 price_id text NOT NULL,
 product_id text NOT NULL,
 amount_cents integer NOT NULL CHECK (amount_cents = 100),
 currency text NOT NULL CHECK (currency = 'usd'),
 livemode boolean NOT NULL DEFAULT false CHECK (livemode = false),
 status text NOT NULL CHECK (status IN ('reserved','open','pending','paid','expired','canceled','failed','blocked')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS tiq_one_checkout_per_run ON tiq_checkouts(run_id);
CREATE TABLE IF NOT EXISTS tiq_payments (
 id uuid PRIMARY KEY,
 checkout_id uuid NOT NULL REFERENCES tiq_checkouts(id),
 stripe_payment_intent_id text NOT NULL UNIQUE,
 stripe_charge_id text UNIQUE,
 amount_cents integer NOT NULL CHECK (amount_cents = 100),
 currency text NOT NULL CHECK (currency = 'usd'),
 livemode boolean NOT NULL CHECK (livemode = false),
 status text NOT NULL CHECK (status IN ('paid','refunded','disputed')),
 verified_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tiq_stripe_events (
 event_id text PRIMARY KEY,
 event_type text NOT NULL,
 event_digest text NOT NULL CHECK (event_digest ~ '^[0-9a-f]{64}$'),
 received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tiq_entitlements (
 id uuid PRIMARY KEY,
 run_id text NOT NULL UNIQUE REFERENCES tiq_runs(id),
 payment_id uuid NOT NULL UNIQUE REFERENCES tiq_payments(id),
 status text NOT NULL CHECK (status IN ('active','refunded','disputed','revoked')),
 report_digest text NOT NULL CHECK (report_digest ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- Restrict all tables to the private backend database role. No public grants.
REVOKE ALL ON tiq_runs, tiq_checkouts, tiq_payments, tiq_stripe_events, tiq_entitlements FROM PUBLIC;
COMMIT;
