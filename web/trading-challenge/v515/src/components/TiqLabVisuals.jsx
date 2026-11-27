import { useState } from "react";

// Visual helpers for the Practice Lab. Everything here is fictional teaching material: no prices are real,
// nothing shows a profit as a reward, and nothing is stored or sent anywhere.

export const KIND_INFO = {
  verified: { label: "Verified", trust: 90, text: "Verified means you can trace it to an original document or an official notice, and independent sources agree. Even then, a verified report is a reason to make a plan, not to rush." },
  rumor: { label: "Rumored", trust: 20, text: "A rumor has no named source and no document. Repetition is not confirmation. The safe habit is to check the original source or wait." },
  screenshot: { label: "Misleading", trust: 10, text: "A misleading image hides the clues that would let you check it, such as the address, the date or the original link. Treat it as untrusted until you find the original." },
  incomplete: { label: "Incomplete", trust: 50, text: "An incomplete report may be real, but the missing part could change the story. Wait for the fuller update before you act." },
};

export function EvidencePanel({ item, kind }) {
  const [shown, setShown] = useState(0);
  const clues = item.clues || [];
  const all = shown >= clues.length;
  const trust = shown === 0 ? null : Math.round((shown / clues.length) * 100);
  return (
    <div className="tiq-evid">
      <button type="button" className="tiq-btn tiq-btn--ghost tiq-evid-btn" aria-expanded={shown > 0} aria-controls={item.id + "-ev"}
        disabled={all} onClick={() => setShown((n) => Math.min(clues.length, n + 1))}>
        {shown === 0 ? "Examine the evidence" : all ? "All evidence examined" : "Reveal the next clue (" + shown + " of " + clues.length + ")"}
      </button>
      <ol id={item.id + "-ev"} className="tiq-evid-list" aria-live="polite">
        {clues.slice(0, shown).map((c) => <li key={c} className="tiq-evid-clue">{c}</li>)}
      </ol>
      <p className="tiq-small">Clues examined: {shown} of {clues.length}. Fictional source and details.</p>
      <div className="tiq-cred" role="img" aria-label={trust === null ? "Source check not started" : "Clues examined " + trust + " percent"}>
        <span className="tiq-cred-fill" style={{ width: (trust || 0) + "%" }} />
      </div>
      {kind && <ClassBadge kind={kind} />}
    </div>
  );
}

export function ClassBadge({ kind, big }) {
  const k = KIND_INFO[kind];
  if (!k) return null;
  return (
    <div className={"tiq-class tiq-class--" + kind + (big ? " tiq-class--big" : "")} role="status">
      <span className="tiq-class-stamp">{k.label}</span>
      <span className="tiq-small">{k.text}</span>
    </div>
  );
}

export function RiskGauge({ ex, units }) {
  const n = Number.isInteger(units) && units > 0 ? units : 0;
  const perUnit = ex.entry - ex.stop;
  const maxLoss = (ex.account * ex.maxLossPct) / 100;
  const risk = Math.round(n * perUnit * 100) / 100;
  const ratio = maxLoss > 0 ? risk / maxLoss : 0;
  const pct = Math.min(200, Math.round(ratio * 100));
  const cost = n * ex.entry;
  const lo = ex.stop - perUnit * 0.3, hi = ex.entry + perUnit * 0.6;
  const y = (p) => 12 + ((hi - p) / (hi - lo)) * 76;
  return (
    <div className="tiq-risk">
      <div className="tiq-gauge" role="img" aria-label={"Planned loss " + risk + " dollars against a limit of " + maxLoss + " dollars, " + pct + " percent of your risk budget"}>
        <span className="tiq-gauge-fill" data-over={ratio > 1 ? "true" : "false"} style={{ width: pct / 2 + "%" }} />
        <span className="tiq-gauge-limit" />
      </div>
      <p className="tiq-small" role="status">Max planned loss: ${risk} of ${maxLoss} budget ({pct}% used){ratio > 1 ? ". Over budget." : "."} Position cost ${Math.round(cost)}{cost > ex.account ? ", more than the account." : "."}</p>
      <svg className="tiq-ladder" viewBox="0 0 220 100" aria-hidden="true" focusable="false">
        <line x1="40" x2="40" y1="10" y2="90" stroke="#3a4a70" strokeWidth="2" />
        <line className="tiq-ladder-entry" x1="40" x2="210" y1={y(ex.entry)} y2={y(ex.entry)} stroke="#F0D78C" strokeWidth="2" />
        <text x="46" y={y(ex.entry) - 4} fill="#F0D78C" fontSize="10">Entry {ex.entry}</text>
        <line className="tiq-ladder-stop" x1="40" x2="210" y1={y(ex.stop)} y2={y(ex.stop)} stroke="#FF8A7A" strokeWidth="2" strokeDasharray="5 3" />
        <text x="46" y={y(ex.stop) + 12} fill="#FF8A7A" fontSize="10">Stop {ex.stop}</text>
        <rect className="tiq-ladder-zone" x="40" width="170" y={y(ex.entry)} height={Math.max(0, y(ex.stop) - y(ex.entry))} fill="#FF8A7A" opacity="0.15" />
      </svg>
    </div>
  );
}

const SIZE = { double: 2, triple: 3, full: 3, plan: 1, pause: 1, keep: 1, rule: 1.25, small: 0.5, wait: 0, skip: 1, exit: 1, lower: 1, remove: 1 };
const THEME = { emo_1: "Revenge trading", emo_2: "Fear of missing out", emo_3: "Overconfidence", emo_4: "Impatience and hope" };

export function DisciplineScene({ ex, value }) {
  const mult = value ? (SIZE[value] ?? 1) : null;
  const risky = value && ex.options.find((o) => o.id === value) && ex.options.find((o) => o.id === value).score < 50;
  return (
    <div className="tiq-scene" data-risky={risky ? "true" : "false"}>
      <p className="tiq-scene-theme">{THEME[ex.id] || "Emotional decision"}</p>
      <div className="tiq-scene-row"><span className="tiq-small">Usual size</span><span className="tiq-scene-bar"><span style={{ width: "33%" }} className="tiq-scene-fill tiq-scene-fill--calm" /></span></div>
      <div className="tiq-scene-row"><span className="tiq-small">Your next size</span><span className="tiq-scene-bar"><span style={{ width: mult === null ? 0 : Math.min(100, (mult / 3) * 100) * 0.99 + "%" }} className={"tiq-scene-fill " + (risky ? "tiq-scene-fill--hot" : "tiq-scene-fill--calm")} /></span></div>
      <p className="tiq-small" role="status">
        {mult === null ? "Choose an answer to see how it changes the size of your next risk." : risky ? "Impulse path: the next surprise would cost more, and a feeling made the choice. No profit is shown because outcomes are not the lesson." : "Safer path: the plan stays in charge and the size of risk stays under control."}
      </p>
    </div>
  );
}
