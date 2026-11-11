// Adults-18+ self-declaration for future paid Trading IQ report checkout (preview).
// This is a self-declaration, NOT independently verified age. No birthdate or
// other personal details are collected. The same rule must be enforced on the
// server before any checkout session is created; the browser check alone is not proof.

export const DECLARATION_VERSION = "2026-11-04-v1";
export const DECLARATION_TEXT =
  "I confirm that I am 18 years of age or older. I understand this is a self-declaration and is not independently verified.";

// Returns { ok: true } or { ok: false, reason }. Fail-closed on anything unexpected.
export function validateAdultDeclaration(input) {
  if (!input || typeof input !== "object") return { ok: false, reason: "missing" };
  if (input.version !== DECLARATION_VERSION) return { ok: false, reason: "outdated_version" };
  if (input.text !== DECLARATION_TEXT) return { ok: false, reason: "text_mismatch" };
  if (input.declared !== true) return { ok: false, reason: "not_declared" };
  const extra = Object.keys(input).filter((k) => !["version", "text", "declared"].includes(k));
  if (extra.length) return { ok: false, reason: "unexpected_fields" };
  return { ok: true };
}

export function buildAdultDeclaration(declared) {
  return { version: DECLARATION_VERSION, text: DECLARATION_TEXT, declared: declared === true };
}
