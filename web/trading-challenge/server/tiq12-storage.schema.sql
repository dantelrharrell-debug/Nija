-- NIJA IONOS 12-round Trading IQ - isolated test-mode storage schema.
-- REVIEW ONLY: never apply to IONOS or an existing billing/trading database.
-- The schema protects integrity; authenticated app code MUST enforce ownership,
-- origin/CSRF, signed Stripe raw-body webhooks and private credentials.
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tiq12_runs (
    run_id TEXT PRIMARY KEY,
    game_version TEXT NOT NULL CHECK(game_version='nija-trading-iq-12-v1'),
    manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
    owner_proof_hash TEXT NOT NULL CHECK(length(owner_proof_hash)=64),
    answers_json TEXT NOT NULL CHECK(json_valid(answers_json) AND json_type(answers_json)='array' AND json_array_length(answers_json)=12),
    adult_confirmed INTEGER NOT NULL CHECK(adult_confirmed=1),
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiq12_checkout_reservations (
    reservation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES tiq12_runs(run_id) ON DELETE RESTRICT,
    stripe_idempotency_key TEXT NOT NULL UNIQUE,
    checkout_session_id TEXT UNIQUE,
    price_id TEXT NOT NULL CHECK(price_id LIKE 'price_%'),
    product_id TEXT NOT NULL CHECK(product_id LIKE 'prod_%'),
    amount_cents INTEGER NOT NULL CHECK(amount_cents=100),
    currency TEXT NOT NULL CHECK(currency='usd'),
    livemode INTEGER NOT NULL CHECK(livemode=0),
    state TEXT NOT NULL CHECK(state IN ('reserved','created','pending','paid','canceled','blocked')),
    created_at TEXT NOT NULL,
    retry_deadline TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiq12_webhook_events (
    stripe_event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    checkout_session_id TEXT,
    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
    received_at TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('applied','ignored','rejected'))
);

CREATE TABLE IF NOT EXISTS tiq12_verified_payments (
    checkout_session_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE REFERENCES tiq12_checkout_reservations(reservation_id) ON DELETE RESTRICT,
    payment_intent_id TEXT NOT NULL UNIQUE,
    charge_id TEXT NOT NULL UNIQUE,
    stripe_event_id TEXT NOT NULL UNIQUE REFERENCES tiq12_webhook_events(stripe_event_id) ON DELETE RESTRICT,
    amount_cents INTEGER NOT NULL CHECK(amount_cents=100),
    currency TEXT NOT NULL CHECK(currency='usd'),
    livemode INTEGER NOT NULL CHECK(livemode=0),
    verified_at TEXT NOT NULL
);

-- Store reversals BEFORE grants too: a reversed payment must never be
-- fulfilled by a delayed/replayed checkout.session.completed webhook.
CREATE TABLE IF NOT EXISTS tiq12_revocations (
    checkout_session_id TEXT PRIMARY KEY,
    stripe_event_id TEXT NOT NULL UNIQUE REFERENCES tiq12_webhook_events(stripe_event_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK(reason IN ('refund','dispute','manual_security_hold')),
    revoked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiq12_report_entitlements (
    run_id TEXT PRIMARY KEY REFERENCES tiq12_runs(run_id) ON DELETE RESTRICT,
    checkout_session_id TEXT NOT NULL UNIQUE REFERENCES tiq12_verified_payments(checkout_session_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK(status IN ('granted','revoked')),
    granted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    CHECK((status='granted' AND revoked_at IS NULL) OR
          (status='revoked' AND revoked_at IS NOT NULL))
);

CREATE TRIGGER IF NOT EXISTS tiq12_no_grant_after_reversal
BEFORE INSERT ON tiq12_report_entitlements
WHEN EXISTS (SELECT 1 FROM tiq12_revocations
             WHERE checkout_session_id=NEW.checkout_session_id)
BEGIN SELECT RAISE(ABORT, 'checkout session already reversed'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_no_regrant
BEFORE UPDATE OF status ON tiq12_report_entitlements
WHEN OLD.status='revoked' AND NEW.status='granted'
BEGIN SELECT RAISE(ABORT, 'revoked entitlement cannot be regranted'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_no_reassign_entitlement
BEFORE UPDATE OF run_id, checkout_session_id ON tiq12_report_entitlements
BEGIN SELECT RAISE(ABORT, 'entitlement identity is immutable'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_no_reassign_payment
BEFORE UPDATE OF reservation_id, checkout_session_id, payment_intent_id, charge_id ON tiq12_verified_payments
BEGIN SELECT RAISE(ABORT, 'payment identity is immutable'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_no_reassign_reservation
BEFORE UPDATE OF run_id, stripe_idempotency_key, checkout_session_id ON tiq12_checkout_reservations
WHEN OLD.checkout_session_id IS NOT NULL OR
     NEW.run_id<>OLD.run_id OR NEW.stripe_idempotency_key<>OLD.stripe_idempotency_key
BEGIN SELECT RAISE(ABORT, 'checkout reservation identity is immutable'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_payment_requires_matching_checkout
BEFORE INSERT ON tiq12_verified_payments
WHEN NOT EXISTS (
    SELECT 1 FROM tiq12_checkout_reservations r
    WHERE r.reservation_id=NEW.reservation_id
      AND r.checkout_session_id=NEW.checkout_session_id
      AND r.livemode=0 AND r.amount_cents=100 AND r.currency='usd'
)
BEGIN SELECT RAISE(ABORT, 'verified payment must match reserved checkout'); END;

CREATE TRIGGER IF NOT EXISTS tiq12_grant_requires_matching_run
BEFORE INSERT ON tiq12_report_entitlements
WHEN NOT EXISTS (
    SELECT 1 FROM tiq12_verified_payments p
      JOIN tiq12_checkout_reservations r ON p.reservation_id=r.reservation_id
    WHERE p.checkout_session_id=NEW.checkout_session_id AND r.run_id=NEW.run_id
)
BEGIN SELECT RAISE(ABORT, 'report grant must match paid run'); END;

-- Prevent out-of-order payment completion events from reinstating access.
CREATE TRIGGER IF NOT EXISTS tiq12_revoke_existing_grant
AFTER INSERT ON tiq12_revocations
BEGIN
  UPDATE tiq12_report_entitlements
  SET status='revoked', revoked_at=NEW.revoked_at
  WHERE checkout_session_id=NEW.checkout_session_id AND status='granted';
END;

CREATE TRIGGER IF NOT EXISTS tiq12_webhook_event_immutable
BEFORE UPDATE ON tiq12_webhook_events
BEGIN SELECT RAISE(ABORT, 'webhook event journal is immutable'); END;
