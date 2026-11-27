// Isolated test-only SQLite adapter. Uses existing tiq12-storage.schema.sql;
// never open, migrate, or write any NIJA production/customer/trading database.
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, existsSync } from 'node:fs';
import { randomBytes, createHash } from 'node:crypto';
import { Upgrade6Error } from './tiq12-upgrade6-security.mjs';

const VERSION = 'nija-trading-iq-12-v1';
const schema = new URL('./tiq12-storage.schema.sql', import.meta.url);
const nowISO = () => new Date().toISOString();
function runId() { return 'run_' + randomBytes(16).toString('hex'); }
function randomId(prefix) { return prefix + randomBytes(16).toString('hex'); }

export class Tiq12Upgrade6Store {
  constructor(filename, { initialize = false } = {}) {
    if (typeof filename !== 'string' || (!filename.startsWith('/') && filename !== ':memory:')) {
      throw new Upgrade6Error('An absolute isolated database filename is required', 503);
    }
    // In this review branch, schema initialization is restricted to synthetic
    // in-memory tests. No code path may perform a disk migration implicitly.
    if (initialize === true && filename !== ':memory:') {
      throw new Upgrade6Error('Persistent migration requires separate approval', 503);
    }
    if (filename !== ':memory:' && !existsSync(filename)) {
      throw new Upgrade6Error('Approved isolated database does not exist', 503);
    }
    this.db = new DatabaseSync(filename);
    this.db.exec('PRAGMA foreign_keys=ON; PRAGMA busy_timeout=3000;');
    if (initialize !== true) {
      // Opening an existing file never implicitly performs schema changes.
      const row = this.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='tiq12_runs'").get();
      if (!row) { this.db.close(); throw new Upgrade6Error('Approved isolated schema is not installed', 503); }
    } else {
      this.db.exec(readFileSync(schema, 'utf8'));
    }
  }
  close() { this.db.close(); }
  transaction(work) {
    this.db.exec('BEGIN IMMEDIATE');
    try { const value = work(); this.db.exec('COMMIT'); return value; }
    catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  createRun({ manifest, answers, ownerProofHash, completedAt = nowISO() }) {
    return this.transaction(() => {
      const id = runId();
      this.db.prepare(`INSERT INTO tiq12_runs
        (run_id,game_version,manifest_digest,owner_proof_hash,answers_json,
         adult_confirmed,created_at,completed_at) VALUES (?,?,?,?,?,1,?,?)`)
        .run(id, VERSION, manifest.digest, ownerProofHash, JSON.stringify(answers), completedAt, completedAt);
      return this.getRun(id);
    });
  }
  getRun(id) {
    const r = this.db.prepare('SELECT * FROM tiq12_runs WHERE run_id=?').get(id);
    return r ? { id: r.run_id, version: r.game_version, manifestDigest: r.manifest_digest,
      ownerProofHash: r.owner_proof_hash, answers: JSON.parse(r.answers_json),
      adultConfirmed: r.adult_confirmed === 1, persisted: true, completedAt: r.completed_at } : null;
  }
  reserveCheckout({ runId: id, priceId, productId, now = nowISO() }) {
    return this.transaction(() => {
      let row = this.db.prepare('SELECT * FROM tiq12_checkout_reservations WHERE run_id=?').get(id);
      if (row) {
        if (row.price_id !== priceId || row.product_id !== productId ||
            row.amount_cents !== 100 || row.currency !== 'usd' || row.livemode !== 0) {
          throw new Upgrade6Error('Reserved checkout offer mismatch',409);
        }
        return row;
      }
      const reservationId = randomId('rsv_'), idempotencyKey = randomId('tiq12_');
      const deadline = new Date(Date.parse(now) + 20 * 60 * 1000).toISOString();
      this.db.prepare(`INSERT INTO tiq12_checkout_reservations
        (reservation_id,run_id,stripe_idempotency_key,checkout_session_id,
         price_id,product_id,amount_cents,currency,livemode,state,created_at,retry_deadline)
         VALUES (?,?,?,NULL,?,?,100,'usd',0,'reserved',?,?)`)
        .run(reservationId, id, idempotencyKey, priceId, productId, now, deadline);
      return this.db.prepare('SELECT * FROM tiq12_checkout_reservations WHERE run_id=?').get(id);
    });
  }
  attachSession(reservationId, sessionId) {
    return this.transaction(() => {
      const row = this.db.prepare('SELECT * FROM tiq12_checkout_reservations WHERE reservation_id=?').get(reservationId);
      if (!row || (row.checkout_session_id && row.checkout_session_id !== sessionId)) {
        throw new Upgrade6Error('Checkout reservation conflict', 409);
      }
      if (row.state === 'blocked' || row.state === 'canceled') {
        throw new Upgrade6Error('Checkout reservation blocked', 409);
      }
      if (!row.checkout_session_id) {
        this.db.prepare("UPDATE tiq12_checkout_reservations SET checkout_session_id=?,state='created' WHERE reservation_id=?")
          .run(sessionId, reservationId);
      }
      return this.db.prepare('SELECT * FROM tiq12_checkout_reservations WHERE reservation_id=?').get(reservationId);
    });
  }
  getCheckoutBySession(sessionId) {
    return this.db.prepare('SELECT * FROM tiq12_checkout_reservations WHERE checkout_session_id=?').get(sessionId) || null;
  }
  hasEvent(eventId) {
    return Boolean(this.db.prepare('SELECT 1 FROM tiq12_webhook_events WHERE stripe_event_id=?').get(eventId));
  }
  // Call ONLY after authenticating the raw Stripe signature AND independently
  // reconciling current Checkout/Price/Intent/Charge state with Stripe.
  recordPaid({ event, rawBody, reservation, paymentIntentId, chargeId, now = nowISO(), expiresAt }) {
    return this.transaction(() => {
      if (this.hasEvent(event.id)) return 'duplicate';
      const hash = createHash('sha256').update(rawBody).digest('hex');
      const sessionId = reservation.checkout_session_id;
      const reversed = this.db.prepare('SELECT 1 FROM tiq12_revocations WHERE checkout_session_id=?').get(sessionId);
      const current = this.db.prepare('SELECT state FROM tiq12_checkout_reservations WHERE reservation_id=?').get(reservation.reservation_id);
      if (!current) throw new Upgrade6Error('Missing checkout reservation',422);
      const blocked = current.state==='blocked' || current.state==='canceled';
      const alreadyPaid = this.db.prepare('SELECT 1 FROM tiq12_verified_payments WHERE checkout_session_id=?').get(sessionId);
      this.db.prepare(`INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)`)
        .run(event.id, event.type, sessionId, hash, now, now, (reversed || blocked || alreadyPaid) ? 'ignored' : 'applied');
      if (reversed) return 'reversed';
      if (blocked) return 'blocked';
      if (alreadyPaid) return 'already_paid';
      this.db.prepare(`INSERT INTO tiq12_verified_payments VALUES (?,?,?,?,?,?,?,?,?)`)
        .run(sessionId, reservation.reservation_id, paymentIntentId, chargeId, event.id, 100, 'usd', 0, now);
      this.db.prepare(`INSERT INTO tiq12_report_entitlements VALUES (?,?,?,?,?,NULL)`)
        .run(reservation.run_id, sessionId, 'granted', now, expiresAt);
      this.db.prepare("UPDATE tiq12_checkout_reservations SET state='paid' WHERE reservation_id=?")
        .run(reservation.reservation_id);
      return 'granted';
    });
  }
  // Signed asynchronous completion is pending, never a paid entitlement.
  recordPending({event,rawBody,reservation,now=nowISO()}) {
    return this.transaction(() => {
      if (this.hasEvent(event.id)) return 'duplicate';
      const row=this.db.prepare('SELECT state FROM tiq12_checkout_reservations WHERE reservation_id=?').get(reservation.reservation_id);
      if (!row) throw new Upgrade6Error('Missing checkout reservation',422);
      const terminal=['paid','blocked','canceled'].includes(row.state);
      this.db.prepare('INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)')
        .run(event.id,event.type,reservation.checkout_session_id,
          createHash('sha256').update(rawBody).digest('hex'),now,now,'ignored');
      if (!terminal) this.db.prepare("UPDATE tiq12_checkout_reservations SET state='pending' WHERE reservation_id=?")
        .run(reservation.reservation_id);
      return terminal?'terminal':'pending';
    });
  }
  recordCheckoutFailure({event,rawBody,reservation,now=nowISO()}) {
    return this.transaction(() => {
      if (this.hasEvent(event.id)) return 'duplicate';
      const row=this.db.prepare('SELECT state FROM tiq12_checkout_reservations WHERE reservation_id=?').get(reservation.reservation_id);
      if (!row) throw new Upgrade6Error('Missing checkout reservation',422);
      this.db.prepare('INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)')
        .run(event.id,event.type,reservation.checkout_session_id,
          createHash('sha256').update(rawBody).digest('hex'),now,now,
          row.state==='paid'?'ignored':'applied');
      if (row.state!=='paid')this.db.prepare("UPDATE tiq12_checkout_reservations SET state='blocked' WHERE reservation_id=?")
        .run(reservation.reservation_id);
      return row.state==='paid'?'already_paid':'blocked';
    });
  }
  // Reversal is sticky, including when it arrives before paid confirmation.
  recordReversal({ event, rawBody, sessionId, reason, now = nowISO() }) {
    if (!['refund','dispute','manual_security_hold'].includes(reason)) {
      throw new Upgrade6Error('Invalid reversal', 422);
    }
    return this.transaction(() => {
      if (this.hasEvent(event.id)) return 'duplicate';
      const hash = createHash('sha256').update(rawBody).digest('hex');
      this.db.prepare('INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)')
        .run(event.id, event.type, sessionId, hash, now, now, 'applied');
      this.db.prepare('INSERT OR IGNORE INTO tiq12_revocations VALUES (?,?,?,?)')
        .run(sessionId, event.id, reason, now);
      return 'revoked';
    });
  }
  recordIgnored(event, rawBody, now = nowISO()) {
    return this.transaction(() => {
      if (this.hasEvent(event.id)) return 'duplicate';
      const hash = createHash('sha256').update(rawBody).digest('hex');
      this.db.prepare('INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)')
        .run(event.id, event.type, null, hash, now, now, 'ignored');
      return 'ignored';
    });
  }
  getGrant(runIdValue) {
    const r = this.db.prepare(`SELECT e.*, p.stripe_event_id, p.verified_at,
      p.amount_cents, p.currency, p.livemode, x.price_id, x.product_id,
      s.manifest_digest, s.owner_proof_hash
      FROM tiq12_report_entitlements e
      JOIN tiq12_verified_payments p ON p.checkout_session_id=e.checkout_session_id
      JOIN tiq12_checkout_reservations x ON x.reservation_id=p.reservation_id
      JOIN tiq12_runs s ON s.run_id=e.run_id
      WHERE e.run_id=? AND NOT EXISTS
      (SELECT 1 FROM tiq12_revocations v WHERE v.checkout_session_id=e.checkout_session_id)`)
      .get(runIdValue);
    if (!r) return null;
    return { persisted:true,providerVerified:true,webhookSignatureVerified:true,
      status:r.status,livemode:r.livemode===1,runId:r.run_id,
      manifestDigest:r.manifest_digest,ownerProofHash:r.owner_proof_hash,
      priceId:r.price_id,productId:r.product_id,amountPaid:r.amount_cents,
      currency:r.currency,checkoutSessionId:r.checkout_session_id,
      stripeEventId:r.stripe_event_id,refunded:false,disputed:false,
      revokedAt:r.revoked_at,verifiedAt:r.verified_at,expiresAt:r.expires_at };
  }
}
