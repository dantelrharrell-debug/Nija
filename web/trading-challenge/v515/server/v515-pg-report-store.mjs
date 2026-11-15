// Sandbox-only v515 owner-scoped durable PostgreSQL adapter.
// The caller supplies an isolated pg.Pool; no connection strings or secrets here.
// All live APIs remain disabled. Run reviewed SQL migration before use.
import {PaidReportDenied} from "./verified-report-service.mjs";
const okId = s => typeof s === "string" && s.length >= 1 && s.length <= 160;
export class V515PgReportStore {
  constructor(pool) {
    if (!pool || typeof pool.connect !== "function") throw new TypeError("pg_pool_required");
    this.pool = pool;
  }
  async getOwnedPurchase(ownerId, runId) {
    if (!okId(ownerId) || !okId(runId)) return null;
    const r = await this.pool.query(`
      SELECT r.owner_id, r.run_id, r.canonical_run, p.reservation_id,
             p.stripe_session, p.state
      FROM tiq72_v515_runs r
      JOIN tiq72_v515_reservations p ON p.run_id = r.run_id
      WHERE r.owner_id=$1 AND p.owner_id=$1 AND r.run_id=$2
        AND r.version='v515-72-decisions'
      LIMIT 1`, [ownerId, runId]);
    const row = r.rows?.[0];
    if (!row) return null;
    return {
      ownerId: row.owner_id, runId: row.run_id, canonicalRun: row.canonical_run,
      reservationId: row.reservation_id, sessionId: row.stripe_session, state: row.state
    };
  }
  // This is a transaction, not an authorization shortcut. Payment proof must
  // already have been independently checked against Stripe. A concurrent refund
  // handler MUST lock the same reservation row and set state='refunded'/'disputed'.
  async storeVerifiedReport({ownerId, runId, sessionId, report}) {
    if (!okId(ownerId) || !okId(runId) || !okId(sessionId) ||
        !sessionId.startsWith("cs_test_") ||
        !report || typeof report !== "object" || Array.isArray(report))
      throw new PaidReportDenied("invalid_report_transaction");
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query(`
        SELECT p.reservation_id, p.state, p.stripe_session
        FROM tiq72_v515_reservations p
        JOIN tiq72_v515_runs r ON r.run_id=p.run_id
        WHERE p.run_id=$1 AND p.owner_id=$2 AND r.owner_id=$2
          AND r.version='v515-72-decisions'
        FOR UPDATE OF p`, [runId, ownerId]);
      const purchase=result.rows?.[0];
      if (!purchase || purchase.state!=="paid" || purchase.stripe_session!==sessionId)
        throw new PaidReportDenied("purchase_revoked_or_changed");
      const insertion = await client.query(`
        INSERT INTO tiq72_v515_reports
          (run_id, reservation_id, owner_id, stripe_session, report)
        VALUES ($1,$2,$3,$4,$5::jsonb)
        ON CONFLICT (run_id) DO NOTHING
        RETURNING run_id`,
        [runId, purchase.reservation_id, ownerId, sessionId, JSON.stringify(report)]);
      if (insertion.rowCount===0) {
        const existing = await client.query(`
          SELECT stripe_session, owner_id, reservation_id
          FROM tiq72_v515_reports WHERE run_id=$1`,[runId]);
        const row=existing.rows?.[0];
        if (!row || row.owner_id!==ownerId ||
            row.stripe_session!==sessionId ||
            row.reservation_id!==purchase.reservation_id)
          throw new PaidReportDenied("conflicting_paid_report");
      }
      await client.query("COMMIT");
      return {stored: insertion.rowCount===1};
    } catch(e) {
      await client.query("ROLLBACK");
      throw e;
    } finally { client.release(); }
  }
}
