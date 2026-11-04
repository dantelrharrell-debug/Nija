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
        { label: "Go all in before it climbs more", feedback: "Chasing a move with all your capital concentrates risk." },
        { label: "Size a small position with a defined exit", feedback: "Position limits and exit planning reduce downside exposure." },
        { label: "Wait for a setup that fits your plan", feedback: "Waiting for evidence avoids acting only on excitement." }
      ]
    },
    {
      id: "drop", category: "risk", round: "02 / 06", tag: "RISK CONTROL",
      title: "A sudden drawdown", caption: "Your fictional position falls through its planned exit level.",
      headline: "VIRTUAL MARKET · Unexpected selloff hits the chart",
      prices: [70,68,72,69,65,58,54,48,42,39,31,28],
      question: "How do you respond?",
      options: [
        { label: "Double the position to win the loss back", feedback: "Adding size to a losing position can compound risk." },
        { label: "Ignore your exit and hope for a rebound", feedback: "Hoping replaces the predefined exit with uncertainty." },
        { label: "Follow the exit rule and reassess", feedback: "Following a defined risk limit preserves decision discipline." }
      ]
    },
    {
      id: "mix", category: "risk", round: "03 / 06", tag: "PORTFOLIO CHOICE",
      title: "One big bet or a balanced plan?", caption: "You have $10,000 in fictional capital and several unrelated opportunities.",
      headline: "VIRTUAL MARKET · Sector rotation creates uncertainty",
      prices: [38,40,43,39,46,42,45,41,47,44,48,46],
      question: "Which portfolio choice is more resilient?",
      options: [
        { label: "Put everything into one popular asset", feedback: "A single position exposes the whole account to one outcome." },
        { label: "Spread exposures and keep a cash reserve", feedback: "Diversification and liquidity help avoid single-outcome dependence." },
        { label: "Open many highly correlated positions", feedback: "Multiple positions are not true diversification when they move together." }
      ]
    },
    {
      id: "rumor", category: "research", round: "04 / 06", tag: "SIGNAL OR NOISE",
      title: "The breaking-news rumor", caption: "A viral screenshot claims a major deal, with no verifiable source.",
      headline: "VIRTUAL MARKET · Unconfirmed rumor spreads online",
      prices: [35,36,35,39,48,44,50,43,52,47,42,40],
      question: "What do you do with the information?",
      options: [
        { label: "Verify the source before changing a plan", feedback: "Independent verification limits the influence of false headlines." },
        { label: "Buy immediately because others are buying", feedback: "Crowd activity is not evidence the claim is true." },
        { label: "Treat the screenshot as confirmed news", feedback: "Unverified screenshots can omit important context." }
      ]
    },
    {
      id: "budget", category: "risk", round: "05 / 06", tag: "POSITION SIZING",
      title: "Choose your risk budget", caption: "Your fictional portfolio is $10,000. This is a single uncertain trade.",
      headline: "VIRTUAL MARKET · Volatility estimate rises",
      prices: [38,44,40,50,42,53,45,54,43,56,47,52],
      question: "Which maximum loss is the most conservative?",
      options: [
        { label: "$1,000 (10% of the portfolio)", feedback: "A 10% loss budget on one idea creates large drawdown exposure." },
        { label: "$100 (1% of the portfolio)", feedback: "A 1% example illustrates smaller defined risk per decision." },
        { label: "$500 (5% of the portfolio)", feedback: "Five percent can still add up quickly across several losses." }
      ]
    },
    {
      id: "reset", category: "discipline", round: "06 / 06", tag: "MENTAL GAME",
      title: "Two losses in a row", caption: "Two fictional positions closed at their risk limits. Your confidence is shaken.",
      headline: "VIRTUAL MARKET · No clear setup after a losing streak",
      prices: [56,52,55,50,54,48,46,51,45,47,44,45],
      question: "What will you do next?",
      options: [
        { label: "Increase size on the next idea to recover fast", feedback: "Revenge trading turns frustration into added exposure." },
        { label: "Pause, review notes, and wait for a valid setup", feedback: "Reviewing decisions helps separate process from short-term results." },
        { label: "Keep trading to avoid missing opportunities", feedback: "Unplanned activity can increase mistakes after losses." }
      ]
    }
  ];
  return { VERSION, scenarios };
});
