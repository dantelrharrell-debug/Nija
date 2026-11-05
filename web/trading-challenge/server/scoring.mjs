import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { scenarios, VERSION } = require("../public/scenarios.js");

const points = [
  [0, 4, 5], [0, 1, 5], [0, 5, 2], [5, 0, 1], [0, 5, 2], [0, 5, 1]
];
const categories = {
  risk: { name: "Risk management", advice: "Practice defining exits, position size, and total portfolio exposure before acting." },
  discipline: { name: "Trading discipline", advice: "Write a simple entry, exit, and pause rule, then use it during simulated practice." },
  research: { name: "Evidence checking", advice: "Compare claims with primary sources and identify what would disprove your thesis." }
};
const lessons = [
  ["A headline is not a trading plan.", "Size comes before potential profit.", "Doing nothing can be a disciplined decision."],
  ["Never use size to erase regret.", "Set an exit before entering.", "Manage the loss you can control."],
  ["Concentration can amplify losses.", "Risk is measured across the portfolio.", "Count independent risks, not tickers."],
  ["Evidence outranks virality.", "Avoid impulse decisions.", "Check original disclosures and reliable sources."],
  ["Know your maximum loss first.", "This is an educational example, not a personalized risk recommendation.", "Consider consecutive losses, not only one trade."],
  ["Losses do not create an obligation to trade.", "Consistency beats urgency.", "A session limit is a valid safeguard."]
];

export function validAnswers(answers) {
  return Array.isArray(answers) && answers.length === scenarios.length &&
    answers.every((n) => Number.isInteger(n) && n >= 0 && n < 3);
}
export function scoreReport(answers) {
  if (!validAnswers(answers)) throw new TypeError("Six valid decisions required");
  const total = { risk: 0, discipline: 0, research: 0 };
  const possible = { risk: 0, discipline: 0, research: 0 };
  const decisions = scenarios.map((s, i) => {
    const chosen = answers[i], item = s.options[chosen], earned = points[i][chosen];
    total[s.category] += earned; possible[s.category] += 5;
    return { title: s.title, selected: item.label, points: earned, feedback: item.feedback, lesson: lessons[i][chosen] };
  });
  const dimensions = Object.keys(categories).map((key) => ({
    key, name: categories[key].name,
    score: Math.round(100 * total[key] / possible[key]),
    advice: categories[key].advice
  }));
  const score = Math.round(100 * Object.values(total).reduce((a, b) => a + b, 0) / (scenarios.length * 5));
  const ranked = dimensions.slice().sort((a, b) => b.score - a.score);
  return {
    version: VERSION, score,
    label: score >= 84 ? "Disciplined strategist" : score >= 60 ? "Developing decision-maker" : "Risk-awareness explorer",
    summary: score >= 84
      ? "You often favored patience, evidence, and defined downside in these simulated situations."
      : score >= 60
        ? "You demonstrated several helpful habits, with room to make your process more consistent."
        : "These scenarios reveal useful opportunities to strengthen risk and decision habits.",
    dimensions, strength: ranked[0].name, growthArea: ranked[ranked.length - 1].name,
    nextStep: ranked[ranked.length - 1].advice, decisions,
    disclaimer: "Educational scenarios and illustrative scoring only. Not financial advice, a psychometric test, or a prediction of actual returns."
  };
}
export { VERSION };
