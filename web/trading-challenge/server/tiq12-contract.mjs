// Backend-only contract for the IONOS 12-round Trading IQ experience.
// It intentionally does not enable checkout, create orders, or define fake IONOS content.
import { createHash, timingSafeEqual } from "node:crypto";

export const TIQ12_VERSION = "nija-trading-iq-12-v1";
export const TIQ12_ROUNDS = 12;
const idPattern = /^[a-z][a-z0-9_-]{1,63}$/;
const hexPattern = /^[a-f0-9]{64}$/;

function fail(message) { throw new TypeError(message); }
function text(value, max = 300) {
  if (typeof value !== "string" || !value.trim() || value.length > max) fail("Invalid manifest text");
  return value;
}
function id(value) {
  if (typeof value !== "string" || !idPattern.test(value)) fail("Invalid identifier");
  return value;
}
function equalDigest(a, b) {
  return typeof a === "string" && typeof b === "string" && hexPattern.test(a) && hexPattern.test(b) &&
    timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
}
export function ownerProofHash(proof) {
  if (typeof proof !== "string" || !hexPattern.test(proof)) fail("Invalid owner proof");
  return createHash("sha256").update(proof, "ascii").digest("hex");
}

// The IONOS export must supply this exact 12-round scoring manifest to the PRIVATE backend.
// Never import it from the browser, Checkout redirect, or customer-supplied API body.
export function validateTiq12Manifest(source) {
  if (!source || source.version !== TIQ12_VERSION || !Array.isArray(source.rounds) ||
      source.rounds.length !== TIQ12_ROUNDS) fail("Canonical 12-round manifest required");
  const seen = new Set();
  const rounds = Array.from(source.rounds, (entry) => {
    const roundId = id(entry?.id);
    if (seen.has(roundId)) fail("Duplicate round ID");
    seen.add(roundId);
    const category = id(entry.category);
    const title = text(entry.title);
    if (!Array.isArray(entry.choices) || entry.choices.length < 2 || entry.choices.length > 6) {
      fail("Invalid choice count");
    }
    const choices = Array.from(entry.choices, (choice) => {
      if (!Number.isInteger(choice?.points) || choice.points < 0 || choice.points > 5) {
        fail("Invalid private scoring points");
      }
      return {
        label: text(choice.label, 160),
        points: choice.points,
        feedback: text(choice.feedback, 600),
        lesson: text(choice.lesson, 300),
      };
    });
    return { id: roundId, category, title, choices };
  });
  // Deterministic digest pins the precise, server-approved scoring ruleset.
  const canonical = JSON.stringify({ version: TIQ12_VERSION, rounds });
  const digest = createHash("sha256").update(canonical).digest("hex");
  return { version: TIQ12_VERSION, rounds, digest };
}

export function validateTiq12Answers(manifest, supplied) {
  if (!manifest || manifest.version !== TIQ12_VERSION ||
      !Array.isArray(manifest.rounds) || manifest.rounds.length !== TIQ12_ROUNDS ||
      !Array.isArray(supplied) || supplied.length !== TIQ12_ROUNDS) {
    fail("Twelve completed server-validated rounds required");
  }
  return Array.from(supplied, (answer, index) => {
    const round = manifest.rounds[index];
    if (!answer || typeof answer !== "object" || Array.isArray(answer) ||
        Object.keys(answer).sort().join(",") !== "choice,roundId" ||
        answer.roundId !== round.id || !Number.isInteger(answer.choice) ||
        answer.choice < 0 || answer.choice >= round.choices.length) {
      fail("Invalid or tampered round response");
    }
    return { roundId: round.id, choice: answer.choice };
  });
}

// Only accepts a run fetched from the backend's durable, authenticated store.
// The consuming API must enforce origin, CSRF, idempotency and rate limits separately.
export function requireAdultCompletedRun(storedRun, manifest) {
  if (!storedRun || storedRun.persisted !== true || storedRun.adultConfirmed !== true ||
      storedRun.version !== TIQ12_VERSION || !equalDigest(storedRun.manifestDigest, manifest?.digest) ||
      typeof storedRun.completedAt !== "string" || !storedRun.completedAt ||
      typeof storedRun.id !== "string" || !idPattern.test(storedRun.id)) {
    fail("Adult-owned completed run required");
  }
  return validateTiq12Answers(manifest, storedRun.answers);
}

// Defense in depth only. Both the completed run and grant MUST be loaded from a
// private, durable database by an authenticated backend, NEVER from a request,
// Checkout redirect, browser localStorage, or unauthenticated event. A boolean
// 'providerVerified' alone is not evidence of a signed webhook; the consuming
// service must authenticate Stripe's raw-body signature, reconcile the payment
// with Stripe, and commit the irreversible audit/event ledger before storing it.
// For Upgrade 6 this function intentionally accepts test-mode grants ONLY.
export function requireVerifiedTiq12Entitlement(manifest, storedRun, entitlement, offer) {
  const answers = requireAdultCompletedRun(storedRun, manifest);
  const isId = (value, kind) => typeof value === "string" &&
    new RegExp("^" + kind + "_[A-Za-z0-9_]{3,250}$").test(value);
  if (!offer || !isId(offer.priceId, "price") || !isId(offer.productId, "prod") ||
      !entitlement || typeof entitlement !== "object" || Array.isArray(entitlement) ||
      entitlement.persisted !== true || entitlement.providerVerified !== true ||
      entitlement.webhookSignatureVerified !== true ||
      entitlement.status !== "granted" || entitlement.livemode !== false ||
      entitlement.runId !== storedRun.id ||
      !equalDigest(entitlement.manifestDigest, manifest.digest) ||
      !equalDigest(entitlement.ownerProofHash, storedRun.ownerProofHash) ||
      entitlement.priceId !== offer.priceId || entitlement.productId !== offer.productId ||
      entitlement.amountPaid !== 100 || entitlement.currency !== "usd" ||
      !isId(entitlement.checkoutSessionId, "cs_test") ||
      !isId(entitlement.stripeEventId, "evt") ||
      entitlement.refunded !== false || entitlement.disputed !== false ||
      entitlement.revokedAt !== null ||
      typeof entitlement.verifiedAt !== "string" ||
      !Number.isFinite(Date.parse(entitlement.verifiedAt))) {
    fail("Durable, verified, unreversed Stripe test entitlement required");
  }
  return answers;
}

// Do not compute a paid report without a matching durable, verified grant.
// This is deliberately a breaking change to the PRIVATE, currently unwired
// 12-round contract; no public game, payment route, or live entitlement changes.
export function scorePurchasedTiq12(manifest, storedRun, entitlement, offer) {
  const answers = requireVerifiedTiq12Entitlement(manifest, storedRun, entitlement, offer);
  const totals = new Map();
  const decisions = answers.map((answer, index) => {
    const round = manifest.rounds[index];
    const choice = round.choices[answer.choice];
    const old = totals.get(round.category) || { points: 0, max: 0 };
    old.points += choice.points;
    old.max += 5;
    totals.set(round.category, old);
    return { roundId: round.id, title: round.title, selected: choice.label,
      points: choice.points, feedback: choice.feedback, lesson: choice.lesson };
  });
  const dimensions = [...totals.entries()].map(([category, total]) => ({
    category, score: Math.round(100 * total.points / total.max),
  }));
  const score = Math.round(100 * decisions.reduce((n, item) => n + item.points, 0) / (TIQ12_ROUNDS * 5));
  return { version: TIQ12_VERSION, manifestDigest: manifest.digest,
    score, dimensions, decisions,
    disclaimer: "Educational simulation only. Not investment advice or a prediction of returns." };
}

// Defense-in-depth receipt check. A signed Stripe webhook and durable, idempotent
// payment/revocation ledger are STILL mandatory before granting any entitlement.
export function matchesVerifiedTiq12Payment({ session, lineItems, proof, storedRun, manifest,
  expectedPriceId, expectedProductId, livemode }) {
  try {
    requireAdultCompletedRun(storedRun, manifest);
    if (typeof expectedPriceId !== "string" || !/^price_[A-Za-z0-9_]+$/.test(expectedPriceId) ||
        typeof expectedProductId !== "string" || !/^prod_[A-Za-z0-9_]+$/.test(expectedProductId) ||
        typeof livemode !== "boolean" ||
        typeof session?.id !== "string" ||
        !new RegExp("^cs_" + (livemode ? "live" : "test") + "_[A-Za-z0-9_]{8,250}$").test(session.id) ||
        typeof proof !== "string" || !hexPattern.test(proof) ||
        !equalDigest(ownerProofHash(proof), storedRun.ownerProofHash) ||
        session?.metadata?.run_id !== storedRun.id ||
        session?.metadata?.game_version !== TIQ12_VERSION ||
        !equalDigest(session?.metadata?.manifest_digest, manifest.digest) ||
        !equalDigest(session?.metadata?.owner_proof_hash, ownerProofHash(proof)) ||
        session?.livemode !== livemode || session?.mode !== "payment" ||
        session?.status !== "complete" || session?.payment_status !== "paid" ||
        session?.amount_total !== 100 || session?.currency !== "usd") return false;
    const intent = session.payment_intent, charge = intent?.latest_charge;
    if (!intent || intent.status !== "succeeded" || intent.amount_received !== 100 ||
        intent.currency !== "usd" || charge?.paid !== true || charge?.refunded !== false ||
        charge?.disputed !== false || charge?.amount_refunded !== 0 ||
        charge?.status !== "succeeded") return false;
    const rows = lineItems?.data;
    if (!Array.isArray(rows) || rows.length !== 1 || lineItems.has_more === true) return false;
    const row = rows[0], price = row.price;
    const priceId = typeof price === "string" ? price : price?.id;
    const productId = typeof price?.product === "string" ? price.product : price?.product?.id;
    return row.quantity === 1 && row.amount_total === 100 && row.currency === "usd" &&
      priceId === expectedPriceId && productId === expectedProductId;
  } catch { return false; }
}
