// Trading IQ scoring (educational, process-only). Pure functions, no storage, no network.
// Simulated investment returns are NEVER used here: the same decisions on the same prices give the same
// score whether the fictional portfolio went up or down. Portfolio value is shown only for illustration.
// Used by the replay engine (official result), the report, and the in-game results screen.

export const clamp = (n) => Math.min(100, Math.max(0, Math.round(n)));
export const band = (n) => (n >= 75 ? "Strong" : n >= 55 ? "Developing" : "Needs work");
export const signalOf = (m) => (m > 0.5 ? "up" : m < -0.5 ? "down" : "flat");

export function fitsLastMove(row) {
  const m = row.lastMovePct / 100;
  if (row.action === "buy") return m >= -0.005;
  if (row.action === "sell") return row.held && m <= 0.005;
  return row.held ? m >= -0.005 : m <= 0.005;
}

// Per challenge: the three behaviours the game can see inside one challenge.
export function challengeAreas(c) {
  const rows = c.decisions;
  const risk = clamp(100 - c.maxDD * 100 * 3 + (c.stopUsed ? 15 : 0));
  const judged = rows.filter((d) => d.round > 1);
  const fits = judged.filter(fitsLastMove).length;
  const research = judged.length ? clamp((fits / judged.length) * 100) : 0;
  const overTrades = Math.max(0, c.trades - 6);
  const unprotectedDrops = rows.filter((d) => d.held && d.action !== "sell" && !d.stopArmed && d.movePct < -0.5).length;
  const emptySells = rows.filter((d) => d.action === "sell" && !d.held).length;
  const discipline = clamp(100 - overTrades * 6 - unprotectedDrops * 6 - emptySells * 5);
  return { risk, research, discipline, fits, judged: judged.length, overTrades, unprotectedDrops, emptySells };
}

// Diversification from what the game really has (one asset per challenge). Returns { score|null, detail }.
export function scoreDiversification(challenges) {
  const exposure = challenges.map((c) => c.decisions.reduce((t, d) => t + d.invested, 0) / c.decisions.length);
  const total = exposure.reduce((t, e) => t + e, 0);
  const peak = Math.max(...challenges.flatMap((c) => c.decisions.map((d) => d.invested)));
  if (!(total > 0.0001)) {
    return { score: null, detail: "Not scored: you never held a position, so there was no invested capital to spread. Multi-asset rounds are not yet available." };
  }
  const hhi = exposure.reduce((t, e) => t + (e / total) ** 2, 0);
  const evenness = Math.min(1, Math.max(0, (1 / hhi - 1) / (challenges.length - 1)));
  const sizeScore = Math.min(1, Math.max(0, 1 - Math.max(0, peak - 0.4) / 0.6));
  return {
    score: clamp(100 * (0.6 * evenness + 0.4 * sizeScore)),
    detail: `Capital spread across challenges ${Math.round(evenness * 100)}/100; largest invested share of the portfolio ${(peak * 100).toFixed(0)}%. One asset per challenge, so this is not multi-asset diversification.`,
  };
}

// Consistency: same visible price signal + same position state -> same action. Returns { score|null, detail }.
export function scoreConsistency(challenges) {
  const groups = new Map();
  for (const c of challenges) {
    for (const d of c.decisions) {
      if (d.round < 2) continue;
      const key = `${signalOf(d.lastMovePct)}|${d.held ? "in" : "cash"}`;
      const g = groups.get(key) ?? { buy: 0, sell: 0, hold: 0 };
      g[d.action] += 1;
      groups.set(key, g);
    }
  }
  let counted = 0, agree = 0;
  for (const g of groups.values()) {
    const n = g.buy + g.sell + g.hold;
    if (n < 2) continue;
    counted += n;
    agree += Math.max(g.buy, g.sell, g.hold);
  }
  if (counted < 6) return { score: null, detail: "Not scored: too few repeated situations to compare your decisions." };
  return { score: clamp((agree / counted) * 100), detail: `${agree} of ${counted} decisions in repeated situations used the action you chose most often in that situation.` };
}

// challenges: [{ maxDD, trades, stopUsed, decisions: [{round, action, held, stopArmed, movePct, lastMovePct, invested}] }]
// Returns the five areas, the Trading IQ (mean of the areas that could be scored) and a score per challenge
// (mean of that challenge's risk, research and discipline).
export function scoreRun(all) {
  // A challenge saved by an older version has no recorded decisions; it cannot be scored on behaviour and is left out.
  const challenges = all.filter((c) => c.decisions && c.decisions.length > 0);
  if (!challenges.length) {
    const none = { score: null, band: "Not scored", detail: "Not scored: no recorded decisions." };
    return { assessments: { risk: none, research: none, discipline: none, diversification: none, consistency: none }, iq: 0, challengeScores: all.map(() => 0), counts: { overTrades: 0, unprotectedDrops: 0, emptySells: 0, fits: 0, judged: 0, avgDD: 0, stopCount: 0 } };
  }
  const per = challenges.map(challengeAreas);
  const n = per.length;
  const mean = (k) => per.reduce((t, p) => t + p[k], 0) / n;
  const avgDD = challenges.reduce((t, c) => t + c.maxDD, 0) / n;
  const stopCount = challenges.filter((c) => c.stopUsed).length;
  const risk = clamp(100 - avgDD * 100 * 3 + (stopCount / n) * 15);
  const fits = per.reduce((t, p) => t + p.fits, 0);
  const judged = per.reduce((t, p) => t + p.judged, 0);
  const research = judged ? clamp((fits / judged) * 100) : 0;
  const overTrades = per.reduce((t, p) => t + p.overTrades, 0);
  const unprotectedDrops = per.reduce((t, p) => t + p.unprotectedDrops, 0);
  const emptySells = per.reduce((t, p) => t + p.emptySells, 0);
  const discipline = clamp(100 - overTrades * 6 - unprotectedDrops * 6 - emptySells * 5);
  const div = scoreDiversification(challenges);
  const con = scoreConsistency(challenges);
  const assessments = {
    risk: { score: risk, band: band(risk), detail: `Average largest drop ${(avgDD * 100).toFixed(1)}%; stop-loss used in ${stopCount} of ${n} challenges.` },
    research: { score: research, band: band(research), detail: `${fits} of ${judged} decisions fit the last price move you could see.` },
    discipline: { score: discipline, band: band(discipline), detail: `${overTrades} extra trades above 6, ${unprotectedDrops} unprotected drops, ${emptySells} attempts to sell with nothing held.` },
    diversification: { score: div.score, band: div.score === null ? "Not scored" : band(div.score), detail: div.detail },
    consistency: { score: con.score, band: con.score === null ? "Not scored" : band(con.score), detail: con.detail },
  };
  const scored = Object.values(assessments).map((a) => a.score).filter((s) => s !== null);
  const iq = clamp(scored.reduce((t, s) => t + s, 0) / scored.length);
  let k = 0;
  const challengeScores = all.map((c) => (c.decisions && c.decisions.length > 0 ? clamp((per[k].risk + per[k++].research + per[k - 1].discipline) / 3) : (Number.isFinite(c.score) ? c.score : 0)));
  return { assessments, iq, challengeScores, counts: { overTrades, unprotectedDrops, emptySells, fits, judged, avgDD, stopCount } };
}

export const IQ_METHOD =
  "Trading IQ is the average of the scorecard areas that could be scored: risk management, research and verification, patience and discipline, diversification and decision consistency. " +
  "Simulated portfolio gains or losses are not part of any score; they are shown only to illustrate the fictional run.";
