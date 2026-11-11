// Report access and preview simulation (preview/staging only, not deployed, nothing stored).
// Real access = completed run + matching owner credential + ACTIVE entitlement created by a verified
// payment event. Simulated purchases are flagged and can never satisfy production access or revenue.
import { canOpenReport, hashOwnerCredential, PRICE_CENTS } from "./tiq_premium_core.mjs";
import { buildReport } from "./tiq_report.mjs";

export const SIMULATION_LABEL = "Preview test — no payment was made";

// Preview-only: creates a flagged record. Never production, never revenue.
export function simulatePreviewPurchase({ run, previewMode }) {
  if (previewMode !== true) return { ok: false, reason: "simulation_disabled" };
  if (!run || run.status !== "completed") return { ok: false, reason: "run_not_completed" };
  return {
    ok: true,
    entitlement: {
      run_id: run.id, status: "active", simulated: true, production: false,
      amount_cents: 0, label: SIMULATION_LABEL,
    },
  };
}

// Only real, verified-payment entitlements count. Simulated and zero-amount records are excluded.
export function countedRevenueCents(entitlements) {
  return entitlements
    .filter((e) => e && e.simulated !== true && e.production !== false && e.status === "active" && e.amount_cents === PRICE_CENTS)
    .reduce((t, e) => t + e.amount_cents, 0);
}

// Re-open a report later. `acceptSimulated` is true only inside the preview.
export function openReport({ run, decisions, entitlement, presentedCredential, serverKey, acceptSimulated = false }) {
  if (entitlement && entitlement.simulated === true && acceptSimulated !== true) {
    return { ok: false, reason: "not_purchased" };
  }
  if (entitlement && entitlement.run_id !== run?.id) return { ok: false, reason: "not_found" };
  const gate = canOpenReport({ run, entitlement, presentedCredential, serverKey });
  if (!gate.ok) return gate;
  const report = buildReport({ mode: run.mode, level: run.level, dayNum: run.mode === "daily" ? run.day_num : 0, challenges: decisions });
  if (!report) return { ok: false, reason: "report_unavailable" };
  if (report.tradingIQ !== run.total_score) return { ok: false, reason: "score_mismatch" };
  return { ok: true, report, simulated: entitlement.simulated === true };
}

export { hashOwnerCredential };
