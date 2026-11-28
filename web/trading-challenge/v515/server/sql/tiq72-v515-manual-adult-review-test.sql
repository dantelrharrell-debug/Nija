-- PROTECTED TEST PREVIEW ONLY. Review separately; do not apply in production.
-- Run with a separate migration role. Runtime needs SELECT/INSERT and identity
-- sequence permissions only, not UPDATE/DELETE or table ownership.
BEGIN;
CREATE TABLE tiq72_v515_manual_adult_reviews (
  review_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  buyer_id TEXT NOT NULL CHECK (buyer_id ~ '^[A-Za-z0-9_.-]{1,160}$'),
  reviewer_id TEXT NOT NULL CHECK (reviewer_id ~ '^[A-Za-z0-9_.-]{1,160}$'),
  decision TEXT NOT NULL CHECK (decision IN ('approve','revoke')),
  decided_at_ms BIGINT NOT NULL CHECK (decided_at_ms >= 0),
  expires_at_ms BIGINT,
  CHECK (buyer_id <> reviewer_id),
  CHECK ((decision = 'revoke' AND expires_at_ms IS NULL) OR
         (decision = 'approve' AND expires_at_ms IS NOT NULL AND
          expires_at_ms > decided_at_ms AND expires_at_ms - decided_at_ms <= 15552000000))
);
CREATE INDEX tiq72_v515_manual_review_latest
  ON tiq72_v515_manual_adult_reviews (buyer_id,review_id DESC);
COMMIT;
