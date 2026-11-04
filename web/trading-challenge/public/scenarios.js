/* NIJA Trading IQ Challenge: fictional education scenarios, no orders or market feeds. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NIJAGame = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const VERSION = "nija-trading-iq-v1";
  const scenarios = [
    {
      id: "hype", category: "discipline", round: "01 / 06", tag: "FOMO CHECK",
      title: "The hype spike", caption: "A fictional asset has climbed quickly after a viral post.",
      headline: "VIRTUAL MARKET · Momentum surges 18% in minutes",
      prices: [30,32,31,35,34,40,45,43,51,54,59,65],
      question: "What is your next move?",
      options: [
        { label: "Go all in before it climbs more", points: 0, feedback: "Chasing a move with all your capital concentrates risk.", lesson: "A headline is not a trading plan." },
        { label: "Size a small position with a defined exit", points: 4, feedback: "Position limits and exit planning reduce downside exposure.", lesson: "Size comes before potential profit." },
        { label: "Wait for a setup that fits your plan", points: 5, feedback: "Waiting for evidence avoids acting only on excitement.", lesson: "Doing nothing can be a disciplined decision." }
      ]
    },
    {
      id: "drop", category: "risk", round: "02 / 06", tag: "RISK CONTROL",
      title: "A sudden drawdown", caption: "Your fictional position falls through its planned exit level.",
      headline: "VIRTUAL MARKET · Unexpected selloff hits the chart",
      prices: [70,68,72,69,65,58,54,48,42,39,31,28],
      question: "How do you respond?",
      options: [
        { label: "Double the position to win the loss back", points: 0, feedback: "Adding size to a losing position can compound risk.", lesson: "Never use size to erase regret." },
        { label: "Ignore your exit and hope for a rebound", points: 1, feedback: "Hoping replaces the predefined exit with uncertainty.", lesson: "Set an exit before entering." },
        { label: "Follow the exit rule and reassess", points: 5, feedback: "Following a defined risk limit preserves decision discipline.", lesson: "Manage the loss you can control." }
      ]
    },
    {
      id: "mix", category: "risk", round: "03 / 06", tag: "PORTFOLIO CHOICE",
      title: "One big bet or a balanced plan?", caption: "You have $10,000 in fictional capital and several unrelated opportunities.",
      headline: "VIRTUAL MARKET · Sector rotation creates uncertainty",
      prices: [38,40,43,39,46,42,45,41,47,44,48,46],
      question: "Which portfolio choice is more resilient?",
      options: [
        { label: "Put everything into one popular asset", points: 0, feedback: "A single position exposes the whole account to one outcome.", lesson: "Concentration can amplify losses." },
        { label: "Spread exposures and keep a cash reserve", points: 5, feedback: "Diversification and liquidity help avoid single-outcome dependence.", lesson: "Risk is measured across the portfolio." },
        { label: "Open many highly correlated positions", points: 2, feedback: "Multiple positions are not true diversification when they move together.", lesson: "Count independent risks, not tickers." }
      ]
    },
    {
      id: "rumor", category: "research", round: "04 / 06", tag: "SIGNAL OR NOISE",
      title: "The breaking-news rumor", caption: "A viral screenshot claims a major deal, with no verifiable source.",
      headline: "VIRTUAL MARKET · Unconfirmed rumor spreads online",
      prices: [35,36,35,39,48,44,50,43,52,47,42,40],
      question: "What do you do with the information?",
      options: [
        { label: "Verify the source before changing a plan", points: 5, feedback: "Independent verification limits the influence of false headlines.", lesson: "Evidence outranks virality." },
        { label: "Buy immediately because others are buying", points: 0, feedback: "Crowd activity is not evidence the claim is true.", lesson: "Avoid impulse decisions." },
        { label: "Treat the screenshot as confirmed news", points: 1, feedback: "Unverified screenshots can omit important context.", lesson: "Check original disclosures and reliable sources." }
      ]
    },
    {
      id: "budget", category: "risk", round: "05 / 06", tag: "POSITION SIZING",
      title: "Choose your risk budget", caption: "Your fictional portfolio is $10,000. This is a single uncertain trade.",
      headline: "VIRTUAL MARKET · Volatility estimate rises",
      prices: [38,44,40,50,42,53,45,54,43,56,47,52],
      question: "Which maximum loss is the most conservative?",
      options: [
        { label: "$1,000 (10% of the portfolio)", points: 0, feedback: "A 10% loss budget on one idea creates large drawdown exposure.", lesson: "Know your maximum loss first." },
        { label: "$100 (1% of the portfolio)", points: 5, feedback: "A 1% example illustrates smaller defined risk per decision.", lesson: "This is an educational example, not a personalized risk recommendation." },
        { label: "$500 (5% of the portfolio)", points: 2, feedback: "Five percent can still add up quickly across several losses.", lesson: "Consider consecutive losses, not only one trade." }
      ]
    },
    {
      id: "reset", category: "discipline", round: "06 / 06", tag: "MENTAL GAME",
      title: "Two losses in a row", caption: "Two fictional positions closed at their risk limits. Your confidence is shaken.",
      headline: "VIRTUAL MARKET · No clear setup after a losing streak",
      prices: [56,52,55,50,54,48,46,51,45,47,44,45],
      question: "What will you do next?",
      options: [
        { label: "Increase size on the next idea to recover fast", points: 0, feedback: "Revenge trading turns frustration into added exposure.", lesson: "Losses do not create an obligation to trade." },
        { label: "Pause, review notes, and wait for a valid setup", points: 5, feedback: "Reviewing decisions helps separate process from short-term results.", lesson: "Consistency beats urgency." },
        { label: "Keep trading to avoid missing opportunities", points: 1, feedback: "Unplanned activity can increase mistakes after losses.", lesson: "A session limit is a valid safeguard." }
      ]
    }
  ];
  const categories = {
    risk: { name: "Risk management", advice: "Practice defining exits, position size, and total portfolio exposure before acting." },
    discipline: { name: "Trading discipline", advice: "Write a simple entry, exit, and pause rule, then use it during simulated practice." },
    research: { name: "Evidence checking", advice: "Compare claims with primary sources and identify what would disprove your thesis." }
  };
  function validAnswers(answers) {
    return Array.isArray(answers) && answers.length === scenarios.length &&
      answers.every((v) => Number.isInteger(v) && v >= 0 && v <= 2);
  }
  function report(answers) {
    if (!validAnswers(answers)) throw new TypeError("Six valid decisions are required");
    const totals = { risk: 0, discipline: 0, research: 0 };
    const max = { risk: 0, discipline: 0, research: 0 };
    const decisions = scenarios.map((s, i) => {
      const choice = s.options[answers[i]];
      totals[s.category] += choice.points;
      max[s.category] += 5;
      return { title: s.title, selected: choice.label, points: choice.points, feedback: choice.feedback, lesson: choice.lesson };
    });
    const dimensions = Object.keys(categories).map((key) => ({
      key, name: categories[key].name,
      score: Math.round(100 * totals[key] / max[key]),
      advice: categories[key].advice
    }));
    const score = Math.round(100 * Object.values(totals).reduce((a,b)=>a+b,0) / (scenarios.length * 5));
    const ordered = dimensions.slice().sort((a,b) => b.score - a.score);
    const low = ordered[ordered.length - 1];
    const high = ordered[0];
    return {
      version: VERSION, score,
      label: score >= 84 ? "Disciplined strategist" : score >= 60 ? "Developing decision-maker" : "Risk-awareness explorer",
      summary: score >= 84
        ? "You often favored patience, evidence, and defined downside in these simulated situations."
        : score >= 60
          ? "You demonstrated several helpful habits, with room to make your process more consistent."
          : "These scenarios reveal useful opportunities to strengthen risk and decision habits.",
      dimensions, strength: high.name, growthArea: low.name,
      nextStep: low.advice, decisions,
      disclaimer: "Educational scenarios and illustrative scoring only. Not financial advice, a psychometric test, or a prediction of actual returns."
    };
  }
  return { VERSION, scenarios, validAnswers, report };
});
