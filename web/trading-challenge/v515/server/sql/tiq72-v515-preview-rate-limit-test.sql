-- Separate TEST preview schema candidate. Never apply with the core migration.
-- Requires explicit database identity and recovery evidence, independent approval,
-- and least-privilege grants to the existing isolated runtime role.
BEGIN;
DO $gate$
BEGIN
  IF current_database() <> 'nija_tiq72_upgrade6_isolated_test' THEN
    RAISE EXCEPTION 'wrong database for isolated TIQ72 preview rate limit';
  END IF;
END
$gate$;
CREATE TABLE public.tiq72_v515_preview_rate_limits (
  lane text PRIMARY KEY,
  window_epoch bigint NOT NULL CHECK (window_epoch >= 0),
  hits smallint NOT NULL CHECK (
    (lane = 'authenticated_commerce' AND hits BETWEEN 1 AND 30) OR
    (lane = 'owner_review' AND hits BETWEEN 1 AND 8)
  )
);
COMMIT;
