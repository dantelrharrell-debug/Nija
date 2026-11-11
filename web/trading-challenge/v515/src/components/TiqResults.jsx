import { SCORECARD_KEYS, SCORECARD_LABEL } from "../lib/tiqReportClient.js";

// Final results hero: the overall Trading IQ (a process score) shown as a ring, plus recommendations drawn only
// from the player's own area scores. Fictional portfolio results are kept in a separate "illustration only" panel.

const TIPS = {
  risk: "Practise sizing each position so a planned loss stays within a limit you set before you start. The Practice Lab Risk Plan exercises are a good place to try this.",
  research: "Before acting, ask where a claim comes from and whether you can find the original. The News Check cards in the Practice Lab train exactly this.",
  discipline: "Write your plan before the round and follow it, especially after a loss or a quick jump in price. The Discipline scenarios in the Practice Lab show the pattern.",
  diversification: "Try spreading a fictional portfolio across assets that do not move together. The Practice Lab allocation exercises show how a spread softens a bad day.",
  consistency: "Aim for steady, repeatable decisions rather than big swings between rounds. Reviewing each round's feedback helps.",
};

export function recommendFrom(assessments) {
  if (!assessments) return [];
  const rows = SCORECARD_KEYS.map((k) => ({ k, score: assessments[k] ? assessments[k].score : null }));
  const scored = rows.filter((r) => typeof r.score === "number").sort((a, b) => a.score - b.score);
  const out = scored.filter((r) => r.score < 80).slice(0, 3).map((r) => ({ k: r.k, score: r.score, text: TIPS[r.k], kind: "improve" }));
  const best = scored[scored.length - 1];
  if (best && best.score >= 70) out.push({ k: best.k, score: best.score, text: "Your strongest area. Keep the habit that earned it.", kind: "strength" });
  const missing = rows.filter((r) => r.score === null);
  for (const m of missing.slice(0, 1)) out.push({ k: m.k, score: null, text: "Not scored yet. " + TIPS[m.k], kind: "unscored" });
  return out;
}

export function ScoreRing({ score, target }) {
  const r = 52, c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, Number(score) || 0));
  return (
    <div className="tiq-ring" role="img" aria-label={"Trading IQ " + v + " out of 100. Level target " + target + "."}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#1c2a4a" strokeWidth="10" />
        <circle className="tiq-ring-arc" cx="60" cy="60" r={r} fill="none" stroke="#D4AF37" strokeWidth="10" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform="rotate(-90 60 60)" style={{ "--circ": c }} />
      </svg>
      <span className="tiq-ring-num" aria-hidden="true">{v}</span>
    </div>
  );
}

export function Recommendations({ assessments }) {
  const recs = recommendFrom(assessments);
  if (recs.length === 0) return <p className="tiq-small">Personalized recommendations appear after a challenge played from the start in this tab.</p>;
  return (
    <section className="tiq-card tiq-card--inner tiq-recs" aria-labelledby="tiq-recs-h">
      <h3 id="tiq-recs-h" className="tiq-fb-head">Your personalized next steps</h3>
      <ul className="tiq-rec-list">
        {recs.map((r, i) => (
          <li key={r.k + r.kind} className={"tiq-rec tiq-rec--" + r.kind} style={{ "--d": i * 120 + "ms" }}>
            <strong>{SCORECARD_LABEL[r.k]}{r.score === null ? "" : ": " + r.score + " / 100"}</strong>
            <span className="tiq-small">{r.text}</span>
          </li>
        ))}
      </ul>
      <p className="tiq-small">Based only on your own process scores. Educational, not financial advice.</p>
    </section>
  );
}

// Full scorecard: the Trading IQ and every area it is built from, each with a bar, a band word and the plain
// reason behind the number. Strengths and improvement opportunities come only from the player's own scores.
export function ScoreCard({ assessments, iq }) {
  if (!assessments) return null;
  const rows = SCORECARD_KEYS.map((k) => ({ k, a: assessments[k] }));
  const strengths = rows.filter((r) => r.a && typeof r.a.score === "number" && r.a.score >= 75);
  const growth = rows.filter((r) => r.a && typeof r.a.score === "number" && r.a.score < 75).sort((x, y) => x.a.score - y.a.score);
  return (
    <section className="tiq-card tiq-card--inner tiq-scorecard" aria-labelledby="tiq-scorecard-h">
      <h3 id="tiq-scorecard-h" className="tiq-fb-head">Your Trading IQ scorecard</h3>
      <p className="tiq-small">Trading IQ {iq} is the average of the areas below that could be scored from your own decisions.</p>
      <ul className="tiq-score-list">
        {rows.map(({ k, a }, i) => {
          const has = a && typeof a.score === "number";
          return (
            <li key={k} className="tiq-score-row" style={{ "--d": i * 110 + "ms" }}>
              <div className="tiq-score-top">
                <strong>{SCORECARD_LABEL[k]}</strong>
                <span className="tiq-score-val">{has ? a.score + " / 100" : "Not scored"} · {a ? a.band : "Not scored"}</span>
              </div>
              <div className="tiq-score-bar" role="presentation"><span style={{ width: (has ? a.score : 0) + "%" }} /></div>
              <p className="tiq-small">{a ? a.detail : ""}</p>
            </li>
          );
        })}
      </ul>
      <div className="tiq-sg">
        <div className="tiq-sg-col">
          <p className="tiq-fb-head">Strengths</p>
          {strengths.length ? (
            <ul>{strengths.map((r) => <li key={r.k} className="tiq-small">{SCORECARD_LABEL[r.k]} ({r.a.score})</li>)}</ul>
          ) : <p className="tiq-small">No area reached 75 yet. Every area can be improved with practice.</p>}
        </div>
        <div className="tiq-sg-col">
          <p className="tiq-fb-head">Improvement opportunities</p>
          {growth.length ? (
            <ul>{growth.map((r) => <li key={r.k} className="tiq-small">{SCORECARD_LABEL[r.k]} ({r.a.score})</li>)}</ul>
          ) : <p className="tiq-small">Every scored area is at 75 or above. Try a higher level.</p>}
        </div>
      </div>
      <p className="tiq-small">Educational scoring of process, never of profit. Not financial advice.</p>
    </section>
  );
}
