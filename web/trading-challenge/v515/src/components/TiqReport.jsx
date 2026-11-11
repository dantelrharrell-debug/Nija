import { Link } from "react-router";
import { actionLabel, reportToHtml, SCORECARD_KEYS, SCORECARD_LABEL } from "../lib/tiqReportClient.js";

export function downloadReport(report, preview) {
  const blob = new Blob([reportToHtml(report, { preview })], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "my-trading-iq-report.html";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function TiqReport({ report, preview, onClose }) {
  return (
    <section className="tiq-card tiq-rise tiq-report" aria-labelledby="tiq-report-h">
      {preview && (
        <p className="tiq-feedback tiq-feedback--caution" role="note">
          <strong>Preview test — no payment was made.</strong> This sample is not a purchase and is not counted as revenue.
        </p>
      )}
      <h2 id="tiq-report-h" className="tiq-h1">Your Trading IQ report</h2>
      <p className="tiq-report-score" aria-label={`Trading IQ ${report.tradingIQ} out of 100`}>{report.tradingIQ}<span>/100</span></p>
      <p className="tiq-small">
        Level {report.level}, target {report.target} — {report.targetMet ? "target met" : "target not yet met"}.
        Fictional prices, virtual money.
      </p>

      <h3 className="tiq-fb-head">Your five-area scorecard</h3>
      <div className="tiq-table-wrap">
        <table className="tiq-table">
          <thead><tr><th scope="col">Area</th><th scope="col">Score</th><th scope="col">Rating</th><th scope="col">Why</th></tr></thead>
          <tbody>
            {SCORECARD_KEYS.map((k) => (
              <tr key={k}><th scope="row">{SCORECARD_LABEL[k]}</th><td>{report.assessments[k].score === null ? "Not scored" : `${report.assessments[k].score}/100`}</td><td>{report.assessments[k].band}</td><td>{report.assessments[k].detail}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="tiq-fb-head">Strengths</h3>
      <ul className="tiq-scenario-list">{report.strengths.map((t) => <li key={t}>{t}</li>)}</ul>
      <h3 className="tiq-fb-head">Weaknesses</h3>
      <ul className="tiq-scenario-list">{report.weaknesses.map((t) => <li key={t}>{t}</li>)}</ul>

      <h3 className="tiq-fb-head">All 12 decisions in every challenge</h3>
      {report.challenges.map((c) => (
        <details key={c.name} className="tiq-report-details">
          <summary>{c.name} — score {c.score}</summary>
          <div className="tiq-table-wrap">
            <table className="tiq-table">
              <thead><tr><th scope="col">Round</th><th scope="col">Your action</th><th scope="col">Price</th><th scope="col">What happened</th></tr></thead>
              <tbody>
                {c.decisions.map((d) => (
                  <tr key={d.round}>
                    <th scope="row">{d.round}</th>
                    <td>{actionLabel(d.action)}{d.stopArmed ? " + stop-loss" : ""}</td>
                    <td>{d.priceBefore} → {d.priceAfter}</td>
                    <td><strong>{d.head}.</strong> {d.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}

      <h3 className="tiq-fb-head">Your improvement steps</h3>
      <ol className="tiq-scenario-list">{report.recommendations.map((t) => <li key={t}>{t}</li>)}</ol>

      <h3 className="tiq-fb-head">Academy lessons to review</h3>
      <ul className="tiq-scenario-list">
        {report.lessons.map((l) => (
          <li key={l.id}><Link to={`/academy/${l.ageGroup}`}>{l.title}</Link> <span className="tiq-small">(Academy, {l.ageGroup.replace("ages-", "ages ")})</span></li>
        ))}
      </ul>

      <h3 className="tiq-fb-head">How the five scorecard areas are calculated</h3>
      <ul className="tiq-scenario-list">{SCORECARD_KEYS.map((k) => <li key={k}><strong>{SCORECARD_LABEL[k]}:</strong> {report.method[k]}</li>)}</ul>

      <div className="tiq-actions">
        <button type="button" className="tiq-btn tiq-btn--gold" onClick={() => downloadReport(report, preview)}>Download report</button>
        <button type="button" className="tiq-btn tiq-btn--ghost" onClick={onClose}>Close report</button>
      </div>
      <p className="tiq-small">{report.disclaimer}</p>
    </section>
  );
}
