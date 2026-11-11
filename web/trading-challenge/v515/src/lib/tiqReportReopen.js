// Browser side of "re-open my purchased report". Not connected: the server route that checks the
// buyer's code and an active, payment-verified purchase is not deployed. Fails closed, no network.
export const REOPEN_AVAILABLE = false;

export function requestReopen({ runId, code }) {
  if (!REOPEN_AVAILABLE) return Promise.resolve({ ok: false, reason: "not_available" });
  if (typeof runId !== "string" || typeof code !== "string") return Promise.resolve({ ok: false, reason: "bad_input" });
  return Promise.resolve({ ok: false, reason: "not_available" });
}

// Preview simulation is allowed only away from the live domain.
export function previewSimulationAllowed(hostname) {
  const h = String(hostname || "").toLowerCase();
  return h === "localhost" || h === "127.0.0.1" || h === "[::1]";
}
