import { useMemo } from "react";
import { evaluateAchievements, compareAttempts, ACHIEVEMENT_NOTICE } from "../lib/tiqExtrasClient.js";
import { SCORECARD_KEYS, SCORECARD_LABEL } from "../lib/tiqReportClient.js";

// Session achievements and attempt comparison. Everything is held in page memory for this visit only.
export default function TiqAchievements({ attempts, onReplay }) {
  const current = attempts[attempts.length - 1];
  const previous = attempts.length > 1 ? attempts[attempts.length - 2] : null;
  const list = useMemo(() => evaluateAchievements(current?.report, previous?.report ?? null), [current, previous]);
  const rows = useMemo(() => compareAttempts(attempts), [attempts]);
  if (!current) return null;
  const earned = list.filter((a) => a.earned).length;
  return (
    <section className="tiq-card tiq-card--inner" aria-labelledby="tiq-ach-h">
      <h3 id="tiq-ach-h" className="tiq-fb-head">Session achievements ({earned} of {list.length})</h3>
      <p className="tiq-small">{ACHIEVEMENT_NOTICE}</p>
      <ul className="tiq-badges">
        {list.map((a) => (
          <li key={a.id} className="tiq-badge" data-earned={a.earned ? "true" : "false"}>
            <span className="tiq-badge-name">{a.earned ? "Earned: " : "Not yet: "}{a.name}</span>
            <span className="tiq-small">{a.how}</span>
          </li>
        ))}
      </ul>
      <h3 className="tiq-fb-head">Your attempts this visit</h3>
      <div className="tiq-table-wrap">
        <table className="tiq-table">
          <caption className="tiq-small">Scorecard by attempt (fictional practice, memory only)</caption>
          <thead>
            <tr>
              <th scope="col">Attempt</th><th scope="col">Trading IQ</th><th scope="col">Change</th>
              {SCORECARD_KEYS.map((k) => <th key={k} scope="col">{SCORECARD_LABEL[k]}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.attempt}>
                <th scope="row">{r.attempt}</th>
                <td>{r.tradingIQ}</td>
                <td>{r.deltaIQ === null ? "—" : (r.deltaIQ > 0 ? "+" : "") + r.deltaIQ}</td>
                {SCORECARD_KEYS.map((k) => <td key={k}>{r.areas[k] === null ? "Not scored" : r.areas[k]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tiq-small">Replay plays the same challenge set again so you can test one improvement at a time. Attempts disappear when you leave or reload this page.</p>
      <div className="tiq-actions">
        <button type="button" className="tiq-btn tiq-btn--ghost" onClick={onReplay}>Replay the same challenges</button>
      </div>
    </section>
  );
}
