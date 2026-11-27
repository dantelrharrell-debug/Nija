import { useEffect, useMemo, useRef, useState } from "react";
import {
  ALLOCATION_EXERCISES, NEWS_KINDS, NEWS_KIND_LABEL, NEWS_RESPONSES, NEWS_ITEMS, POSITION_EXERCISES, LOSS_EXERCISES, STOP_EXERCISES,
  EMOTION_EXERCISES, newsSet, scoreAllocation, stressImpact, scoreLab, mergeScorecard, labAnswerCount, emptyLab, cleanLabResults,
  createLabStore, LAB_STORAGE_DISCLOSURE, LAB_DISCLAIMER, LAB_METHOD, LAB_AREAS, MIN_INVESTED, maxUnits, buildLabCoach, evaluateLabAchievements,
} from "../lib/tiqLabClient.js";
import { EvidencePanel, RiskGauge, DisciplineScene } from "./TiqLabVisuals.jsx";
import { SCORECARD_KEYS, SCORECARD_LABEL } from "../lib/tiqReportClient.js";

// Practice Lab: fictional exercises about spreading money, judging news, sizing risk and staying disciplined.
// Scores are about process, never simulated results. Answers live in page memory; they are written to this browser
// only if the player turns saving on (see LAB_STORAGE_DISCLOSURE). Nothing is sent anywhere, nothing is bought.

function browserStorage() {
  try { return typeof window !== "undefined" ? window.localStorage : null; } catch (e) { return null; }
}

export function useLabController() {
  const store = useMemo(() => createLabStore(browserStorage()), []);
  const [init] = useState(() => store.load());
  const [lab, setLab] = useState(init.lab);
  const [saveOn, setSaveOn] = useState(() => init.enabled === true);
  const [saveOk, setSaveOk] = useState(null);
  useEffect(() => {
    if (saveOn) setSaveOk(store.save(lab));
  }, [lab, saveOn, store]);
  return {
    lab, saveOn, saveOk,
    setAnswer: (group, id, value) => setLab((p) => cleanLabResults({ ...p, [group]: { ...p[group], [id]: value } })),
    removeAnswer: (group, id) => setLab((p) => { const g = { ...p[group] }; delete g[id]; return cleanLabResults({ ...p, [group]: g }); }),
    clearAll: () => setLab(emptyLab()),
    setSave: (on) => {
      setSaveOn(on);
      if (on) setSaveOk(store.save(lab));
      else { store.clear(); setSaveOk(null); }
    },
  };
}

function Feedback({ item, innerRef }) {
  if (!item) return null;
  return (
    <div ref={innerRef} tabIndex={-1} role="status" aria-live="polite" className="tiq-feedback tiq-feedback--note tiq-lab-fb">
      <p className="tiq-fb-head">Feedback on your answer</p>
      <p className="tiq-small">{item.saw}</p>
      <p className="tiq-small">{item.explain}</p>
      <p className="tiq-small"><strong>Principle: {item.principle}</strong></p>
      <p className="tiq-small">{item.alternative}</p>
      {item.extra.map((t) => <p key={t} className="tiq-small">{t}</p>)}
    </div>
  );
}

// Focus moves to the feedback box right after the player checks an answer (keyboard and screen reader users).
function useFocusAfterCheck(saved) {
  const fbRef = useRef(null);
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current && saved !== undefined && fbRef.current) { fbRef.current.focus(); asked.current = false; }
  }, [saved]);
  return { fbRef, markAsked: () => { asked.current = true; } };
}

const coachFor = (group, id, value) => buildLabCoach({ [group]: { [id]: value } }).items[0];

function AllocationItem({ ex, saved, onSave, onClear }) {
  const [draft, setDraft] = useState(() => Object.fromEntries(ex.assets.map((a) => [a.id, saved ? String(saved[a.id] || 0) : ""])));
  const { fbRef, markAsked } = useFocusAfterCheck(saved);
  const parsed = ex.assets.map((a) => {
    const t = draft[a.id].trim();
    return t === "" ? 0 : /^\d{1,3}$/.test(t) ? Number(t) : NaN;
  });
  const bad = parsed.some((n) => Number.isNaN(n));
  const total = bad ? NaN : parsed.reduce((t, n) => t + n, 0);
  const valid = !bad && total <= 100;
  const check = () => {
    if (!valid) return;
    markAsked();
    onSave(Object.fromEntries(ex.assets.map((a, i) => [a.id, parsed[i]])));
  };
  const result = saved ? scoreAllocation(ex.id, saved) : null;
  const stress = saved ? stressImpact(ex.id, saved) : null;
  return (
    <fieldset className="tiq-lab-item">
      <legend className="tiq-lab-legend">{ex.title}</legend>
      <p className="tiq-small">{ex.brief}</p>
      <ul className="tiq-lab-assets">
        {ex.assets.map((a) => (
          <li key={a.id} className="tiq-lab-asset">
            <label htmlFor={`${ex.id}-${a.id}`}><strong>{a.name}</strong><span className="tiq-small"> {a.note}</span></label>
            <span className="tiq-lab-pct">
              <input id={`${ex.id}-${a.id}`} className="tiq-lab-input" type="text" inputMode="numeric" pattern="[0-9]*" autoComplete="off"
                maxLength={3} disabled={!!saved} value={draft[a.id]} placeholder="0"
                onChange={(e) => setDraft((d) => ({ ...d, [a.id]: e.target.value }))} aria-describedby={`${ex.id}-sum`} />
              <span aria-hidden="true">%</span>
            </span>
          </li>
        ))}
      </ul>
      <svg className="tiq-spark" viewBox="0 0 200 50" aria-hidden="true" focusable="false">
        {ex.assets.map((a, i) => { const pts = [0,1,2,3,4,5,6,7,8,9].map((t) => { const base = Math.sin((t + i * 1.7) * 0.9) * (6 + i * 3) + (i % 2 ? -t : t) * 1.2; return (t * 20 + 5) + "," + (25 - base); }).join(" "); return <polyline key={a.id} className={"tiq-spark-line tiq-mix-stroke--" + (i % 5)} points={pts} pathLength="1" fill="none" strokeWidth="2.2" style={{ opacity: (Number.isNaN(parsed[i]) ? 0 : parsed[i]) > 0 ? 1 : 0.25 }} />; })}
      </svg>
      <p className="tiq-small">Fictional sample movements, illustration only. Different assets rise and fall at different times, which is why a spread can soften a bad day.</p>
      <div className="tiq-mix" aria-hidden="true">
        {ex.assets.map((a, i) => (
          <span key={a.id} className={"tiq-mix-seg tiq-mix-seg--" + (i % 5)} style={{ width: (Number.isNaN(parsed[i]) ? 0 : Math.min(100, parsed[i])) + "%" }} title={a.name + " " + (parsed[i] || 0) + "%"} />
        ))}
        <span className="tiq-mix-cash" />
      </div>
      <p id={`${ex.id}-sum`} className="tiq-small" role="status">
        {bad ? "Use whole numbers from 0 to 100." : total > 100 ? `Over by ${total - 100}%. The total cannot pass 100%.` : `Invested ${total}%. Cash left ${100 - total}%.`}
      </p>
      {!saved && <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--gold" disabled={!valid} onClick={check}>Check my mix</button></div>}
      {saved && (
        <>
          <p className="tiq-small"><strong>{result.score === null ? "Not scored" : `Spread score: ${result.score} out of 100`}</strong></p>
          {stress && (
            <p className="tiq-small">
              Fictional what-if ({stress.name}): your mix would move about {stress.portfolioChangePct > 0 ? "+" : ""}{stress.portfolioChangePct}%.
              This is for learning only. It is not a prediction and it is not part of your score.
            </p>
          )}
          <Feedback item={coachFor("allocation", ex.id, saved)} innerRef={fbRef} />
          <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--ghost" onClick={onClear}>Try a different mix</button></div>
        </>
      )}
    </fieldset>
  );
}

function RadioGroup({ name, options, value, onChange, disabled }) {
  return (
    <div className="tiq-lab-opts">
      {options.map((o) => (
        <label key={o.id} className="tiq-lab-opt" data-on={value === o.id ? "true" : "false"}>
          <input type="radio" name={name} value={o.id} checked={value === o.id} disabled={disabled} onChange={() => onChange(o.id)} />
          <span>{o.label}</span>
        </label>
      ))}
    </div>
  );
}

function NewsCard({ item, saved, onSave, onClear }) {
  const [kind, setKind] = useState(saved ? saved.kind : "");
  const [resp, setResp] = useState(saved ? saved.response : "");
  const { fbRef, markAsked } = useFocusAfterCheck(saved);
  const kinds = NEWS_KINDS.map((k) => ({ id: k, label: NEWS_KIND_LABEL[k] }));
  return (
    <fieldset className="tiq-lab-item">
      <legend className="tiq-lab-legend">News item</legend>
      <p className="tiq-small"><strong>Source:</strong> {item.source}</p>
      <p className="tiq-lab-headline">{item.headline}</p>
      <p className="tiq-small">{item.body}</p>
      <EvidencePanel item={item} kind={saved ? item.kind : null} />
      <p className="tiq-small tiq-lab-q" id={`${item.id}-q1`}>1. What kind of report is this?</p>
      <div role="radiogroup" aria-labelledby={`${item.id}-q1`}>
        <RadioGroup name={`${item.id}-kind`} options={kinds} value={kind} onChange={setKind} disabled={!!saved} />
      </div>
      <p className="tiq-small tiq-lab-q" id={`${item.id}-q2`}>2. What do you do?</p>
      <div role="radiogroup" aria-labelledby={`${item.id}-q2`}>
        <RadioGroup name={`${item.id}-resp`} options={NEWS_RESPONSES} value={resp} onChange={setResp} disabled={!!saved} />
      </div>
      {!saved && (
        <div className="tiq-actions">
          <button type="button" className="tiq-btn tiq-btn--gold" disabled={!kind || !resp} onClick={() => { markAsked(); onSave({ kind, response: resp }); }}>Check my answer</button>
        </div>
      )}
      {saved && (
        <>
          <Feedback item={coachFor("news", item.id, saved)} innerRef={fbRef} />
          <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => { setKind(""); setResp(""); onClear(); }}>Answer again</button></div>
        </>
      )}
    </fieldset>
  );
}

function PositionItem({ ex, saved, onSave, onClear }) {
  const [text, setText] = useState(saved ? String(saved) : "");
  const { fbRef, markAsked } = useFocusAfterCheck(saved);
  const n = /^\d{1,7}$/.test(text.trim()) ? Number(text.trim()) : NaN;
  const valid = Number.isInteger(n) && n >= 1;
  return (
    <fieldset className="tiq-lab-item">
      <legend className="tiq-lab-legend">{ex.title}</legend>
      <p className="tiq-small">{ex.brief}</p>
      <RiskGauge ex={ex} units={saved ? saved : n} />
      <label className="tiq-small" htmlFor={`${ex.id}-units`}>Units to buy (whole number)</label>
      <input id={`${ex.id}-units`} className="tiq-lab-input tiq-lab-input--wide" type="text" inputMode="numeric" pattern="[0-9]*" autoComplete="off"
        disabled={!!saved} value={text} onChange={(e) => setText(e.target.value)} />
      {!saved && <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--gold" disabled={!valid} onClick={() => { markAsked(); onSave(n); }}>Check my size</button></div>}
      {saved && (
        <>
          <p className="tiq-small">A rule of thumb to try next time: units = loss limit ÷ (entry price − exit price). Here the limit allows up to {maxUnits(ex)} units.</p>
          <Feedback item={coachFor("position", ex.id, saved)} innerRef={fbRef} />
          <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => { setText(""); onClear(); }}>Try another size</button></div>
        </>
      )}
    </fieldset>
  );
}

function ChoiceItem({ group, ex, saved, onSave, onClear }) {
  const [val, setVal] = useState(saved || "");
  const { fbRef, markAsked } = useFocusAfterCheck(saved);
  return (
    <fieldset className="tiq-lab-item">
      <legend className="tiq-lab-legend">{ex.title}</legend>
      <p className="tiq-small">{ex.brief}</p>
      {group === "emotion" && <DisciplineScene ex={ex} value={val} />}
      <RadioGroup name={ex.id} options={ex.options} value={val} onChange={setVal} disabled={!!saved} />
      {!saved && <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--gold" disabled={!val} onClick={() => { markAsked(); onSave(val); }}>Check my answer</button></div>}
      {saved && (
        <>
          <Feedback item={coachFor(group, ex.id, saved)} innerRef={fbRef} />
          <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => { setVal(""); onClear(); }}>Answer again</button></div>
        </>
      )}
    </fieldset>
  );
}

// Merged five-area scorecard. Base = the game's assessments (or null). Areas without evidence read "Not scored".
export function TiqLabScorecard({ lab, base }) {
  const sc = useMemo(() => scoreLab(lab), [lab]);
  const merged = useMemo(() => mergeScorecard(base || null, sc), [base, sc]);
  const coach = useMemo(() => buildLabCoach(lab), [lab]);
  if (labAnswerCount(lab) === 0 && !base) return null;
  return (
    <section className="tiq-card tiq-card--inner tiq-lab-card" aria-labelledby="tiq-lab-sc-h">
      <h3 id="tiq-lab-sc-h" className="tiq-fb-head">Five-area scorecard{labAnswerCount(lab) > 0 ? " with Practice Lab" : ""}</h3>
      <ul className="tiq-meters" aria-label="Five skill meters, process scores only">
        {SCORECARD_KEYS.map((k, i) => (
          <li key={k} className="tiq-meter" style={{ "--d": i * 120 + "ms" }}>
            <span className="tiq-meter-name">{SCORECARD_LABEL[k]}</span>
            <span className="tiq-meter-track"><span className="tiq-meter-fill" style={{ width: (merged[k].score === null ? 0 : merged[k].score) + "%" }} /></span>
            <span className="tiq-meter-val">{merged[k].score === null ? "Not scored" : merged[k].score + " / 100"}</span>
          </li>
        ))}
      </ul>
      <div className="tiq-table-wrap">
        <table className="tiq-table">
          <caption className="tiq-small">Process scores out of 100. Fictional practice. Never based on simulated results.</caption>
          <thead><tr><th scope="col">Area</th><th scope="col">Score</th><th scope="col">Level</th><th scope="col">Source</th></tr></thead>
          <tbody>
            {SCORECARD_KEYS.map((k) => (
              <tr key={k}>
                <th scope="row">{SCORECARD_LABEL[k]}</th>
                <td>{merged[k].score === null ? "Not scored" : merged[k].score}</td>
                <td>{merged[k].band}</td>
                <td>{merged[k].source === "game+lab" ? "Game + Lab" : merged[k].source === "lab" ? "Practice Lab" : merged[k].source === "game" ? "Game" : "No evidence yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {SCORECARD_KEYS.filter((k) => merged[k].score === null).length > 0 && (
        <p className="tiq-small">Areas marked Not scored have no evidence yet. Diversification needs a Practice Lab mix with at least {MIN_INVESTED}% invested.</p>
      )}
      {labAnswerCount(lab) > 0 && <p className="tiq-small"><strong>{coach.focus}</strong></p>}
      <details className="tiq-report-details">
        <summary>How the Practice Lab scores are worked out</summary>
        {LAB_AREAS.map((k) => <p key={k} className="tiq-small"><strong>{SCORECARD_LABEL[k]}.</strong> {LAB_METHOD[k]}</p>)}
      </details>
    </section>
  );
}

function SavePanel({ ctl }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <section className="tiq-card tiq-card--inner tiq-lab-card" aria-labelledby="tiq-lab-save-h">
      <h3 id="tiq-lab-save-h" className="tiq-fb-head">Keep my Practice Lab answers (optional)</h3>
      <label className="tiq-check">
        <input type="checkbox" checked={ctl.saveOn} onChange={(e) => ctl.setSave(e.target.checked)} />
        <span>Save my Practice Lab answers on this device</span>
      </label>
      <p className="tiq-small">{LAB_STORAGE_DISCLOSURE}</p>
      {ctl.saveOn && ctl.saveOk === true && <p className="tiq-small" role="status"><strong>Saved on this device.</strong> Clearing browser data will remove it.</p>}
      {ctl.saveOn && ctl.saveOk === false && <p className="tiq-small" role="status">This browser would not let us save. You can keep practising; answers stay only until you leave this page.</p>}
      {labAnswerCount(ctl.lab) > 0 && (confirming ? (
        <div role="group" aria-labelledby="tiq-lab-clear-q">
          <p id="tiq-lab-clear-q" className="tiq-fb-head">Clear all Practice Lab answers?</p>
          <p className="tiq-small">This removes your answers here{ctl.saveOn ? " and the saved copy on this device" : ""}. It cannot be undone.</p>
          <div className="tiq-actions">
            <button type="button" className="tiq-btn" onClick={() => { ctl.clearAll(); setConfirming(false); }}>Yes, clear answers</button>
            <button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="tiq-actions"><button type="button" className="tiq-btn tiq-btn--ghost" onClick={() => setConfirming(true)}>Clear my answers</button></div>
      ))}
    </section>
  );
}

const SECTIONS = [
  { key: "portfolio", label: "Portfolio mix" },
  { key: "news", label: "News check" },
  { key: "risk", label: "Risk plan" },
  { key: "discipline", label: "Discipline" },
];

export default function TiqLab({ ctl, base, onClose }) {
  const [section, setSection] = useState("portfolio");
  const headRef = useRef(null);
  useEffect(() => {
    if (typeof window !== "undefined") window.scrollTo(0, 0);
    if (headRef.current) headRef.current.focus();
  }, []);
  const news = useMemo(() => newsSet(0), []);
  const ach = useMemo(() => evaluateLabAchievements(ctl.lab), [ctl.lab]);
  const earned = ach.filter((a) => a.earned).length;
  const { lab, setAnswer, removeAnswer } = ctl;
  return (
    <>
      <section className="tiq-card tiq-lab-card tiq-rise" aria-labelledby="tiq-lab-h">
        <h1 id="tiq-lab-h" ref={headRef} tabIndex={-1} className="tiq-h1">PRACTICE LAB</h1>
        <p className="tiq-lead">Short fictional exercises on spreading money, judging news, sizing risk and staying calm. Scores reward good process, never simulated results.</p>
        <p className="tiq-small">{LAB_DISCLAIMER}</p>
        <div className="tiq-lab-tabs" role="group" aria-label="Practice Lab sections">
          {SECTIONS.map((s) => (
            <button key={s.key} type="button" className="tiq-lab-tab" aria-pressed={section === s.key} onClick={() => setSection(s.key)}>{s.label}</button>
          ))}
        </div>

        {section === "portfolio" && (
          <div>
            <p className="tiq-small">Spreading money across assets that do not all move together can limit the damage when one idea is wrong. Diversification is only scored when you invest at least {MIN_INVESTED}% of the portfolio.</p>
            {ALLOCATION_EXERCISES.map((ex) => (
              <AllocationItem key={ex.id} ex={ex} saved={lab.allocation[ex.id]} onSave={(w) => setAnswer("allocation", ex.id, w)} onClear={() => removeAnswer("allocation", ex.id)} />
            ))}
          </div>
        )}
        {section === "news" && (
          <div>
            <p className="tiq-small">All companies and headlines below are invented. Decide what kind of report each one is, then what you would do.</p>
            {news.map((it) => (
              <NewsCard key={it.id} item={it} saved={lab.news[it.id]} onSave={(a) => setAnswer("news", it.id, a)} onClear={() => removeAnswer("news", it.id)} />
            ))}
            <p className="tiq-small">{NEWS_ITEMS.length - news.length} more fictional news items are kept for later practice.</p>
          </div>
        )}
        {section === "risk" && (
          <div>
            <p className="tiq-small">Decide the maximum loss and the exit before you enter. Then size the position so that hitting the exit stays within your limit.</p>
            {LOSS_EXERCISES.map((ex) => (
              <ChoiceItem key={ex.id} group="loss" ex={ex} saved={lab.loss[ex.id]} onSave={(v) => setAnswer("loss", ex.id, v)} onClear={() => removeAnswer("loss", ex.id)} />
            ))}
            {STOP_EXERCISES.map((ex) => (
              <ChoiceItem key={ex.id} group="stop" ex={ex} saved={lab.stop[ex.id]} onSave={(v) => setAnswer("stop", ex.id, v)} onClear={() => removeAnswer("stop", ex.id)} />
            ))}
            {POSITION_EXERCISES.map((ex) => (
              <PositionItem key={ex.id} ex={ex} saved={lab.position[ex.id]} onSave={(v) => setAnswer("position", ex.id, v)} onClear={() => removeAnswer("position", ex.id)} />
            ))}
          </div>
        )}
        {section === "discipline" && (
          <div>
            <p className="tiq-small">Four moments where emotions push against a plan. Choose what you would really do.</p>
            {EMOTION_EXERCISES.map((ex) => (
              <ChoiceItem key={ex.id} group="emotion" ex={ex} saved={lab.emotion[ex.id]} onSave={(v) => setAnswer("emotion", ex.id, v)} onClear={() => removeAnswer("emotion", ex.id)} />
            ))}
          </div>
        )}
      </section>

      <TiqLabScorecard lab={lab} base={base} />

      <section className="tiq-card tiq-card--inner tiq-lab-card" aria-labelledby="tiq-lab-ach-h">
        <h3 id="tiq-lab-ach-h" className="tiq-fb-head">Practice Lab achievements ({earned} of {ach.length})</h3>
        <p className="tiq-small">Learning markers only: no prizes, no cash value, none is given for doing more.</p>
        <ul className="tiq-badges">
          {ach.map((a) => (
            <li key={a.id} className="tiq-badge" data-earned={a.earned ? "true" : "false"}>
              <span className="tiq-badge-name">{a.earned ? "Earned: " : "Not yet: "}{a.name}</span>
              <span className="tiq-small">{a.how}</span>
            </li>
          ))}
        </ul>
      </section>

      <SavePanel ctl={ctl} />

      <div className="tiq-actions">
        <button type="button" className="tiq-btn" onClick={onClose}>Back to the game</button>
      </div>
    </>
  );
}
