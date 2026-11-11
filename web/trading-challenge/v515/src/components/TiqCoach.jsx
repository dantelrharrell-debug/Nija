import { useMemo } from "react";
import { Link } from "react-router";
import { buildCoach } from "../lib/tiqExtrasClient.js";
import { actionLabel } from "../lib/tiqReportClient.js";
import { DECLARATION_TEXT } from "../lib/adultDeclaration.js";

// NIJA AI Coach: fixed, reviewed wording chosen by rules (not generative AI). Memory only.
// Lesson links appear only when `adult` is true (valid 18+ self-declaration) and only point to adult Academy programs.
export default function TiqCoach({ report, adult, declared, onDeclare }) {
  const coach = useMemo(() => buildCoach(report, { adult: adult === true }), [report, adult]);
  if (!coach) return null;
  return (
    <section className="tiq-card tiq-card--inner tiq-coach" aria-labelledby="tiq-coach-h">
      <h3 id="tiq-coach-h" className="tiq-fb-head">NIJA AI Coach — decision by decision</h3>
      <p className="tiq-small">{coach.notice}</p>
      <p className="tiq-small"><strong>{coach.focus}</strong></p>
      <label className="tiq-small tiq-coach-declare">
        <input type="checkbox" checked={declared} onChange={(e) => onDeclare(e.target.checked)} />
        <span>Show free Academy lessons for adults. {DECLARATION_TEXT}</span>
      </label>
      {!adult && <p className="tiq-small">Lesson links stay hidden unless the adult confirmation above is ticked.</p>}
      {adult && coach.focusLesson && (
        <p className="tiq-small">Free lesson for your focus point: <Link to={coach.focusLesson.path}>{coach.focusLesson.title}</Link></p>
      )}
      {coach.items.map((c) => (
        <details key={c.name} className="tiq-report-details">
          <summary>{c.name}</summary>
          <ol className="tiq-coach-list">
            {c.decisions.map((d) => (
              <li key={d.round} className="tiq-coach-item">
                <p className="tiq-small"><strong>Round {d.round}: {actionLabel(d.action)}.</strong> {d.saw}.</p>
                <p className="tiq-small">{d.explain}</p>
                <p className="tiq-small"><strong>Risk principle: {d.principle.name}.</strong> {d.principle.text}</p>
                <p className="tiq-small">{d.alternative}</p>
                {d.lesson && (
                  <p className="tiq-small">Free Academy lesson: <Link to={d.lesson.path}>{d.lesson.title}</Link></p>
                )}
              </li>
            ))}
          </ol>
        </details>
      ))}
    </section>
  );
}
