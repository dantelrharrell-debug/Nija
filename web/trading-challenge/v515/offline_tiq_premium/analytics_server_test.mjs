import * as A from "./analytics_server_core.mjs";
let p = 0, f = 0; const t = (n, c) => { c ? p++ : (f++, console.log("FAIL", n)); };
const h = (c) => c.repeat(32); const mk = () => ({ events: new Map(), stripe: [] });
const ev = (o = {}) => ({ event: "tiq_game_start", visitor_id: h("a"), run_id: h("b"), event_id: h("c"), consent: true, ...o });
const admin = { id: "u1", collection: "users", role: "admin" };
// authorization
t("unauth 401", A.simulatedSummary(mk(), null).status === 401);
t("anon id-less 401", A.simulatedSummary(mk(), {}).status === 401);
t("member 403", A.simulatedSummary(mk(), { id: "u2", collection: "users", role: "member" }).status === 403);
t("superuser token 403", A.simulatedSummary(mk(), { id: "s", collection: "_superusers", role: "admin" }).status === 403);
t("admin 200", A.simulatedSummary(mk(), admin).status === 200);
// validation
for (const [n, b] of [["null", null], ["array", []], ["extra", ev({ email: "a@b.c" })], ["birthdate", ev({ birthdate: "2000" })], ["bad event", ev({ event: "x" })], ["bad visitor", ev({ visitor_id: "zz" })], ["bad id", ev({ event_id: "1" })], ["no run", ev({ run_id: undefined })], ["bad variant", ev({ variant: "<s>" })]])
  t("reject " + n, A.recordEvent(mk(), b).status === 400);
t("no consent not stored", (() => { const s = mk(); const r = A.recordEvent(s, ev({ consent: false })); return r.status === 204 && s.events.size === 0; })());
t("missing consent not stored", (() => { const s = mk(); const b = ev(); delete b.consent; return A.recordEvent(s, b).status === 204 && s.events.size === 0; })());
// duplicates and separate counts
const s = mk();
t("first recorded", A.recordEvent(s, ev()).body.recorded === true);
t("replay ignored", A.recordEvent(s, ev()).body.duplicate === true && s.events.size === 1);
A.recordEvent(s, ev({ event_id: h("d"), run_id: h("e") }));
A.recordEvent(s, ev({ event_id: h("1"), visitor_id: h("2"), run_id: h("3") }));
const c = A.realSummary(s);
t("visitors 2", c.uniqueVisitors === 2); t("runs 3", c.uniqueRuns === 3);
t("visitors != runs", c.uniqueVisitors !== c.uniqueRuns);
t("no PII stored", ![...s.events.values()].some((r) => "email" in r || "consent" in r || "birthdate" in r));
// simulated separation
const s2 = mk(); A.recordEvent(s2, ev({ variant: "sim_a" }));
t("sim excluded from real", A.realSummary(s2).uniqueVisitors === 0);
t("sim shown to admin", A.simulatedSummary(s2, admin).body.uniqueVisitors === 1);
// payments
const good = { source: "stripe_server", livemode: true, amount_cents: 100, payment_ref: "pi_1" };
t("no stripe data UNVERIFIED", A.revenue(undefined).status === "UNVERIFIED" && A.revenue(undefined).netCents === null);
t("empty UNVERIFIED not zero", A.revenue([]).grossCents === null);
t("verified counts", A.revenue([good]).grossCents === 100);
for (const [n, x] of [["client redirect", { source: "client" }], ["test mode", { livemode: false }], ["test flag", { test: true }], ["simulated", { simulated: true }], ["zero", { amount_cents: 0 }], ["string amount", { amount_cents: "100" }], ["fake ref", { payment_ref: "cs_1" }], ["negative", { amount_cents: -100 }]])
  t("fabricated " + n + " excluded", A.revenue([{ ...good, ...x }]).status === "UNVERIFIED");
t("duplicate payment once", A.revenue([good, good]).grossCents === 100);
t("refund", A.revenue([{ ...good, refunded_cents: 100 }]).netCents === 0);
t("refund capped", A.revenue([{ ...good, refunded_cents: 900 }]).refundCents === 100);
t("dispute", A.revenue([{ ...good, disputed: true }]).netCents === 0);
t("revenue not from events", A.realSummary(s).revenue.status === "UNVERIFIED");
console.log(`PASS: ${p}, FAIL: ${f}`); process.exit(f ? 1 : 0);
