import {randomUUID} from "node:crypto";
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


  // One persistent run per authenticated owner + idempotency attempt.
  // Rejects a reused attempt key with changed decisions, rather than
  // overwriting the original canonical score or creating a second checkout.
  async reserveAuthenticatedRun({ownerId,attemptKey,canonicalRun,canonicalDigest}) {
    if(!okId(ownerId)||!okId(attemptKey)||
       !/^[a-f0-9]{64}$/.test(canonicalDigest)||
       !canonicalRun||typeof canonicalRun!=="object"||Array.isArray(canonicalRun))
      throw new PaidReportDenied("invalid_run_reservation");
    const client=await this.pool.connect();
    const runId=randomUUID(),reservationId=randomUUID();
    try{
      await client.query("BEGIN");
      const inserted=await client.query(`
        INSERT INTO tiq72_v515_runs
         (run_id,owner_id,canonical_run,canonical_digest,attempt_key,version)
        VALUES ($1,$2,$3::jsonb,$4,$5,'v515-72-decisions')
        ON CONFLICT (owner_id,attempt_key) DO NOTHING
        RETURNING run_id`,
        [runId,ownerId,JSON.stringify(canonicalRun),canonicalDigest,attemptKey]);
      if(inserted.rowCount===1){
        await client.query(`
          INSERT INTO tiq72_v515_reservations
          (reservation_id,run_id,owner_id,state)
          VALUES ($1,$2,$3,'reserved')`,
          [reservationId,runId,ownerId]);
        await client.query("COMMIT");
        return {runId,reservationId,sessionId:null,state:"reserved"};
      }
      const original=await client.query(`
        SELECT r.run_id,r.canonical_digest,p.reservation_id,
               p.stripe_session,p.state
        FROM tiq72_v515_runs r JOIN tiq72_v515_reservations p
          ON p.run_id=r.run_id AND p.owner_id=r.owner_id
        WHERE r.owner_id=$1 AND r.attempt_key=$2
        FOR UPDATE OF r,p`,[ownerId,attemptKey]);
      const row=original.rows?.[0];
      if(!row||row.canonical_digest!==canonicalDigest)
        throw new PaidReportDenied("attempt_payload_conflict");
      await client.query("COMMIT");
      return {runId:row.run_id,reservationId:row.reservation_id,
        sessionId:row.stripe_session,state:row.state};
    }catch(e){await client.query("ROLLBACK");throw e;}
    finally{client.release();}
  }
  async attachVerifiedTestCheckout({reservationId,ownerId,sessionId}) {
    if(!okId(reservationId)||!okId(ownerId)||
       !okId(sessionId)||!sessionId.startsWith("cs_test_"))
      throw new PaidReportDenied("invalid_test_checkout");
    const client=await this.pool.connect();
    try{
      await client.query("BEGIN");
      const result=await client.query(`
        SELECT reservation_id,owner_id,stripe_session,state
        FROM tiq72_v515_reservations
        WHERE reservation_id=$1 AND owner_id=$2 FOR UPDATE`,
        [reservationId,ownerId]);
      const row=result.rows?.[0];
      if(!row||!["reserved","checkout_created"].includes(row.state)||
         (row.stripe_session&&row.stripe_session!==sessionId))
        throw new PaidReportDenied("checkout_reservation_changed");
      await client.query(`
        UPDATE tiq72_v515_reservations
        SET stripe_session=$3,state='checkout_created',updated_at=now()
        WHERE reservation_id=$1 AND owner_id=$2`,
        [reservationId,ownerId,sessionId]);
      await client.query("COMMIT");
      return {attached:true};
    }catch(e){await client.query("ROLLBACK");throw e;}
    finally{client.release();}
  }

  // Protected recovery by authenticated owner + run identity, never by a
  // bearer session ID in a URL. The caller must establish the user session.
  // Existing report bytes stay immutable; refund/dispute denies readback.
  async getOwnedPaidReport(ownerId,runId) {
    if(!okId(ownerId)||!okId(runId))
      throw new PaidReportDenied("authenticated_report_owner_required");
    const result=await this.pool.query(`
      SELECT d.report
      FROM tiq72_v515_reports d
      JOIN tiq72_v515_reservations p
        ON p.reservation_id=d.reservation_id AND p.run_id=d.run_id
      JOIN tiq72_v515_runs r
        ON r.run_id=d.run_id AND r.owner_id=d.owner_id
      WHERE d.owner_id=$1 AND d.run_id=$2
        AND p.owner_id=$1 AND p.state='paid'
        AND p.stripe_session=d.stripe_session
        AND r.version='v515-72-decisions'
      LIMIT 1`,[ownerId,runId]);
    return result.rows?.[0]?.report ?? null;
  }

  // Signed events are verified with fresh Stripe retrieval BEFORE reaching here.
  // A row lock serializes payment, reversal and report creation; a terminal
  // refund/dispute can never be re-granted by a late checkout webhook.
  async recordVerifiedProviderEvent({eventId,eventType,reservationId,sessionId}) {
    const paymentEvents = ["checkout.session.completed","checkout.session.async_payment_succeeded"];
    const reverseEvents = ["charge.refunded","charge.dispute.created"];
    if (!okId(eventId) || !eventId.startsWith("evt_") ||
        !okId(reservationId) || !okId(sessionId) ||
        !sessionId.startsWith("cs_test_") ||
        ![...paymentEvents,...reverseEvents].includes(eventType))
      throw new PaidReportDenied("invalid_verified_event");
    const client=await this.pool.connect();
    try {
      await client.query("BEGIN");
      const locked=await client.query(`
        SELECT reservation_id, stripe_session, state
        FROM tiq72_v515_reservations
        WHERE reservation_id=$1 FOR UPDATE`,[reservationId]);
      const purchase=locked.rows?.[0];
      if (!purchase || purchase.reservation_id!==reservationId ||
          purchase.stripe_session!==sessionId)
        throw new PaidReportDenied("reservation_session_mismatch");
      const inserted=await client.query(`
        INSERT INTO tiq72_v515_verified_events
          (event_id,event_type,reservation_id,stripe_session)
        VALUES ($1,$2,$3,$4)
        ON CONFLICT (event_id) DO NOTHING RETURNING event_id`,
        [eventId,eventType,reservationId,sessionId]);
      if (!inserted.rowCount) {
        const previous=await client.query(`
          SELECT event_type,reservation_id,stripe_session
          FROM tiq72_v515_verified_events WHERE event_id=$1`,[eventId]);
        const p=previous.rows?.[0];
        if (!p || p.event_type!==eventType ||
            p.reservation_id!==reservationId || p.stripe_session!==sessionId)
          throw new PaidReportDenied("provider_event_replay_conflict");
        await client.query("COMMIT");
        return {duplicate:true,state:purchase.state};
      }
      let next;
      if (paymentEvents.includes(eventType)) {
        // Stripe delivers events out of order. Receipt is durable, but late
        // success must never restore a refunded or disputed entitlement.
        if (purchase.state==="refunded"||purchase.state==="disputed")
          next=purchase.state;
        else if (["checkout_created","paid"].includes(purchase.state))
          next="paid";
        else throw new PaidReportDenied("checkout_not_reserved");
      } else if (eventType==="charge.dispute.created") {
        next="disputed";
      } else {
        next=purchase.state==="disputed"?"disputed":"refunded";
      }
      await client.query(`
        UPDATE tiq72_v515_reservations SET state=$2,updated_at=now()
        WHERE reservation_id=$1`,[reservationId,next]);
      await client.query("COMMIT");
      return {duplicate:false,state:next};
    } catch(e) {
      await client.query("ROLLBACK");
      throw e;
    } finally {client.release();}
  }
}
