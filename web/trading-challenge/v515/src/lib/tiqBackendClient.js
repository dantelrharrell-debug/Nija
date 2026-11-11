// Client interface STUB for the separate game backend described in
// offline_tiq_premium/GAME_BACKEND_INTEGRATION_SPEC.md (section 2: daily challenges, scores recomputed server-side).
//
// STATUS: NOT CONNECTED. No server exists, `game.nijaaitrading.com` does not resolve, and these functions make NO
// network request. They return { ok:false, reason:"not_available" } so the game stays fully playable offline.
// Only the two calls named in the spec exist here; nothing else is invented (no Practice Lab, progress, classroom,
// analytics or payment endpoints are specified, so none are stubbed). No keys, tokens or secrets belong in this file.
//
// To connect later (separate, owner-approved step): set BACKEND_ORIGIN to the verified HTTPS origin, set
// BACKEND_ENABLED to true, implement the two fetches, and keep every failure path returning the same shape.
export const BACKEND_ENABLED = false;
export const BACKEND_ORIGIN = null; // e.g. "https://game.nijaaitrading.com" once DNS, HTTPS and health are verified

const NOT_AVAILABLE = Object.freeze({ ok: false, reason: "not_available" });

// Spec: GET /daily -> { day, scenarios[6], engine_version }. Public, no personal data.
export async function fetchDaily() {
  return NOT_AVAILABLE;
}

// Spec: POST /runs/:id/submit with decisions only ({ mode, level, dayNum, challenges }). The server replays them and
// returns authoritative scores; scores sent by the browser are ignored by design.
export async function submitRun(/* runId, run */) {
  return NOT_AVAILABLE;
}
