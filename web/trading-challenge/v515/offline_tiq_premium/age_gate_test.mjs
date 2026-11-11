// Server-side adult-gate tests (preview, offline, mocked checkout). Run from app/:
//   node offline_tiq_premium/age_gate_test.mjs
import { readFileSync } from "node:fs";
import * as G from "./age_gate_core.mjs";
const client = await import("../src/lib/adultDeclaration.js");

let pass = 0, fail = 0;
const eq = (n, a, b) => { if (JSON.stringify(a) === JSON.stringify(b)) pass++; else { fail++; console.log("FAIL", n, JSON.stringify(a), JSON.stringify(b)); } };
const ok = (n, c) => { if (c) pass++; else { fail++; console.log("FAIL", n); } };

const NOW = 1_700_000_000_000;
const completedRun = () => ({ id: "a1b2c3d4e5f60718293a4b5c6d7e8f90", status: "completed", expires_at: NOW + 30 * 86400000 });
const good = () => ({ version: G.AGE_GATE_VERSION, text: G.AGE_GATE_TEXT, declared: true });

// Mocked checkout creator: counts calls, returns a fake session id.
function mockCreator() {
  const m = { calls: 0, last: null, fn: null };
  m.fn = (params) => { m.calls++; m.last = params; return { id: "cs_test_mock_" + m.calls }; };
  return m;
}
function attempt(confirmation, extra = {}) {
  const m = mockCreator();
  const res = G.planAgeGatedCheckout({
    confirmation, run: extra.run ?? completedRun(), existingCheckouts: extra.existing ?? [],
    mode: extra.mode ?? "test", now: NOW, createSession: m.fn,
  });
  return { res, calls: m.calls, last: m.last };
}

// ---- valid ----
{
  const a = attempt(good());
  eq("valid: accepted", a.res.ok, true);
  eq("valid: one session created", a.calls, 1);
  eq("valid: charge is $1 USD", [a.last.amount_cents, a.last.currency], [100, "usd"]);
  eq("valid: evidence is self-attestation only", Object.keys(a.res.evidence).sort(), ["age_gate_version", "confirmed_at", "kind"]);
  eq("valid: evidence kind", a.res.evidence.kind, "self_attestation");
  ok("valid: evidence has no wording or personal fields", !JSON.stringify(a.res.evidence).includes("18 years") && !/birth|dob|age"/.test(JSON.stringify(a.res.evidence)));
}

// ---- missing ----
for (const [label, body] of [["undefined", undefined], ["null", null]]) {
  const a = attempt(body);
  eq(`missing (${label}): refused`, a.res.reason, "missing");
  eq(`missing (${label}): no session`, a.calls, 0);
}
{
  const a = attempt({ version: G.AGE_GATE_VERSION, text: G.AGE_GATE_TEXT });
  eq("missing declared field: refused", a.res.reason, "missing");
  eq("missing declared field: no session", a.calls, 0);
}

// ---- false ----
{
  const a = attempt({ ...good(), declared: false });
  eq("false declaration: refused", a.res.reason, "not_declared");
  eq("false declaration: no session", a.calls, 0);
}

// ---- malformed ----
const malformed = [
  ["string true", { ...good(), declared: "true" }],
  ["number 1", { ...good(), declared: 1 }],
  ["version not string", { ...good(), version: 2 }],
  ["text not string", { ...good(), text: ["x"] }],
  ["array body", [good()]],
  ["string body", "18 yes"],
  ["number body", 18],
  ["empty object", {}],
];
for (const [label, body] of malformed) {
  const a = attempt(body);
  eq(`malformed (${label}): refused`, ["malformed", "missing"].includes(a.res.reason), true);
  eq(`malformed (${label}): no session`, a.calls, 0);
}

// ---- outdated / altered wording ----
{
  const a = attempt({ ...good(), version: "2025-01-01-v0" });
  eq("outdated version: refused", a.res.reason, "outdated_version");
  eq("outdated version: no session", a.calls, 0);
}
{
  const a = attempt({ ...good(), text: "I am over 18." });
  eq("altered wording: refused", a.res.reason, "text_mismatch");
  eq("altered wording: no session", a.calls, 0);
}

// ---- unexpected fields, including birthdate ----
for (const field of ["birthdate", "dob", "age", "date_of_birth", "id_number", "passport", "name"]) {
  const a = attempt({ ...good(), [field]: "x" });
  eq(`extra field ${field}: refused`, a.res.reason, "unexpected_fields");
  eq(`extra field ${field}: no session`, a.calls, 0);
}

// ---- validation runs before any other check ----
{
  const a = attempt({ ...good(), declared: false }, { existing: [{ id: "c1", status: "paid", created_at: NOW }] });
  eq("declaration checked before 'already paid'", a.res.reason, "not_declared");
  eq("declaration checked before 'already paid': no session", a.calls, 0);
}

// ---- valid declaration but payment rules still apply ----
{
  const a = attempt(good(), { mode: "live" });
  eq("live mode with valid declaration: payments disabled", a.res.reason, "payments_disabled");
  eq("live mode: no session", a.calls, 0);
}
{
  const a = attempt(good(), { existing: [{ id: "c1", status: "paid", created_at: NOW }] });
  eq("already paid: refused", a.res.reason, "already_paid");
  eq("already paid: no session", a.calls, 0);
}
{
  const a = attempt(good(), { run: { id: "b1b2c3d4e5f60718293a4b5c6d7e8f90", status: "open" } });
  eq("open run: refused", a.res.reason, "run_not_completed");
  eq("open run: no session", a.calls, 0);
}
{
  const a = attempt(good(), { existing: [{ id: "c9", status: "created", created_at: NOW - 60000 }] });
  eq("open checkout reused, not duplicated", [a.res.reason, a.calls], ["reuse_open_checkout", 0]);
}

// ---- failure in session creation never reports success ----
{
  const res = G.planAgeGatedCheckout({
    confirmation: good(), run: completedRun(), existingCheckouts: [], mode: "test", now: NOW,
    createSession: () => { throw new Error("boom"); },
  });
  eq("session creator throws: not ok", res.ok, false);
  eq("session creator throws: safe reason", res.reason, "session_failed");
}
{
  const res = G.planAgeGatedCheckout({
    confirmation: good(), run: completedRun(), existingCheckouts: [], mode: "test", now: NOW,
    createSession: () => ({}),
  });
  eq("session without id: not ok", res.ok, false);
}
{
  const res = G.planAgeGatedCheckout({ confirmation: good(), run: completedRun(), mode: "test", now: NOW });
  eq("no session creator: refused", res.reason, "no_session_creator");
}

// ---- fuzz: 30 random malformed bodies never reach the creator ----
let seed = 42;
const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const pick = (xs) => xs[Math.floor(rnd() * xs.length)];
let fuzzLeak = 0;
for (let i = 0; i < 30; i++) {
  const body = {
    version: pick([G.AGE_GATE_VERSION, "x", "", null, 1]),
    text: pick([G.AGE_GATE_TEXT, "", null]),
    declared: pick([true, false, "true", 1, null, undefined]),
    ...(rnd() > 0.7 ? { birthdate: "2000-01-01" } : {}),
  };
  const isValid = body.version === G.AGE_GATE_VERSION && body.text === G.AGE_GATE_TEXT && body.declared === true && !("birthdate" in body);
  const a = attempt(body);
  if (!isValid && a.calls !== 0) fuzzLeak++;
  if (isValid && a.calls !== 1) fuzzLeak++;
}
eq("fuzz: creator called only for valid bodies", fuzzLeak, 0);

// ---- client and server share the exact approved wording and version ----
eq("client version matches server", client.DECLARATION_VERSION, G.AGE_GATE_VERSION);
eq("client text matches server", client.DECLARATION_TEXT, G.AGE_GATE_TEXT);
eq("client-built declaration passes server gate", G.validateAgeConfirmation(client.buildAdultDeclaration(true)).ok, true);
eq("client unticked declaration refused by server", G.validateAgeConfirmation(client.buildAdultDeclaration(false)).reason, "not_declared");
ok("wording states self-declaration", G.AGE_GATE_TEXT.includes("self-declaration"));

// ---- candidate is not wired to any live route or storage ----
const candidateSrc = readFileSync(new URL("./age_gate_core.mjs", import.meta.url), "utf8");
ok("no route registration in candidate", !/routerAdd|onRecordCreate|\$app\./.test(candidateSrc));
ok("no fetch or network in candidate", !/fetch\(|http|https:/.test(candidateSrc));

console.log(`PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail ? 1 : 0);
