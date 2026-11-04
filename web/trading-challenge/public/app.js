(function () {
  "use strict";
  const { scenarios } = window.NIJAGame;
  const el = (id) => document.getElementById(id);
  const panels = ["intro", "play", "finish", "report", "loading"];
  let round = 0;
  let answers = [];
  let selected = false;
  let verifiedReport = null;
  let pendingSessionId = null;
  let checkoutReady = false;
  const isNative = Boolean(window.Capacitor && typeof window.Capacitor.isNativePlatform === "function" && window.Capacitor.isNativePlatform());
  async function checkCheckout() {
    if (isNative) return;
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      checkoutReady = data.checkoutConfigured === true;
    } catch {
      checkoutReady = false;
    }
    if (!el("finish").classList.contains("hidden") && !pendingSessionId) setPurchaseState();
  }
  function setPurchaseState() {
    const ready = !isNative && checkoutReady;
    el("unlock").disabled = !ready;
    el("unlock").textContent = ready ? "Unlock full report · $1.00 ↗" : "Personalized report · coming soon";
    text("payment-message", isNative
      ? "Native purchases require Apple or Google in-app billing. You can keep playing for free."
      : ready ? "" : "Secure payment is being prepared. The free game remains available.");
  }
  let virtualBalance = 10000;
  const cash = (v) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v);

  function show(id) {
    panels.forEach((name) => el(name).classList.toggle("hidden", name !== id));
    if (id !== "intro") {
      const panel = el(id);
      const headingId = panel.getAttribute("aria-labelledby");
      const target = headingId ? el(headingId) : panel;
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
      panel.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
    }
  }
  function text(id, value) { el(id).textContent = String(value); }
  function node(tag, attrs = {}, content) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "className") element.className = value;
      else if (key === "title") element.title = value;
      else element.setAttribute(key, value);
    }
    if (content !== undefined) element.textContent = String(content);
    return element;
  }
  function clear(element) { element.replaceChildren(); }
  function chart(prices) {
    const svg = el("chart");
    clear(svg);
    const ns = "http://www.w3.org/2000/svg";
    const low = Math.min(...prices) - 4, high = Math.max(...prices) + 4;
    const points = prices.map((v, i) => [i * 640 / (prices.length - 1), 205 - (v - low) / (high - low) * 170]);
    for (let i = 0; i < 5; i++) {
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", "0"); line.setAttribute("x2", "640");
      line.setAttribute("y1", String(35 + i * 43)); line.setAttribute("y2", String(35 + i * 43));
      line.setAttribute("stroke", "#373021"); line.setAttribute("stroke-dasharray", "4 8");
      svg.append(line);
    }
    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", "M" + points.map(p => p.join(",")).join(" L") + " L640,240 L0,240 Z");
    area.setAttribute("fill", "#d4af3720"); svg.append(area);
    const curve = document.createElementNS(ns, "polyline");
    curve.setAttribute("points", points.map(p => p.join(",")).join(" "));
    curve.setAttribute("fill", "none"); curve.setAttribute("stroke", "#f4d06f");
    curve.setAttribute("stroke-linejoin", "round"); curve.setAttribute("stroke-linecap", "round");
    curve.setAttribute("stroke-width", "3.5"); svg.append(curve);
    const last = points[points.length - 1];
    const marker = document.createElementNS(ns, "circle");
    marker.setAttribute("cx", String(last[0])); marker.setAttribute("cy", String(last[1]));
    marker.setAttribute("r", "6"); marker.setAttribute("fill", "#f4d06f"); svg.append(marker);
  }
  function renderRound() {
    selected = false;
    const s = scenarios[round];
    text("balance", cash(virtualBalance));
    text("round-counter", "ROUND " + (round + 1) + " OF " + scenarios.length);
    text("streak", "DECISIONS MADE " + answers.length);
    el("progress-bar").style.width = (100 * round / scenarios.length) + "%";
    text("round-tag", s.tag); text("round-title", s.title);
    text("round-caption", s.caption); text("headline", s.headline);
    text("question", s.question);
    const options = el("options");
    clear(options);
    s.options.forEach((option, index) => {
      const button = node("button", { type: "button", className: "option", "aria-label": option.label });
      button.append(node("b", {}, String.fromCharCode(65 + index)), node("span", {}, option.label));
      button.addEventListener("click", () => choose(index));
      options.append(button);
    });
    el("next").classList.add("hidden");
    el("feedback").classList.add("hidden");
    chart(s.prices);
    show("play");
  }
  function choose(index) {
    if (selected) return;
    selected = true;
    const s = scenarios[round];
    answers.push(index);
    const change = s.options[index].virtualDelta;
    virtualBalance += change;
    text("balance", cash(virtualBalance));
    text("balance-delta", (change >= 0 ? "+" : "−") + cash(Math.abs(change)) + " · fictional outcome");
    el("balance-delta").classList.toggle("negative", change < 0);
    Array.from(el("options").children).forEach((button, i) => {
      button.disabled = true;
      button.classList.toggle("selected", i === index);
      button.setAttribute("aria-pressed", String(i === index));
    });
    const feedback = el("feedback");
    clear(feedback);
    feedback.append(node("strong", {}, "DECISION REVIEW"), node("p", {}, s.options[index].feedback));
    feedback.classList.remove("hidden");
    text("next", round === scenarios.length - 1 ? "See challenge summary →" : "Next market moment →");
    el("next").classList.remove("hidden");
    el("progress-bar").style.width = 100 * answers.length / scenarios.length + "%";
  }
  function finish() {
    text("free-summary", "You finished with " + cash(virtualBalance) + " in fictional capital. Short-term simulated P&L does not determine decision quality. Unlock the optional $1 analysis of risk, research, and discipline.");
    setPurchaseState();
    show("finish");
  }
  function start() {
    answers = []; round = 0; selected = false; verifiedReport = null; pendingSessionId = null; virtualBalance = 10000;
    text("balance-delta", "Simulation starts here");
    el("balance-delta").classList.remove("negative");
    window.history.replaceState({}, "", window.location.pathname);
    renderRound();
  }
  function next() {
    if (!selected) return;
    round += 1;
    if (round < scenarios.length) renderRound();
    else finish();
  }
  async function pay() {
    if (pendingSessionId) return verifyPayment(pendingSessionId);
    if (!checkoutReady || isNative) return;
    if (answers.length !== scenarios.length) return;
    text("payment-message", "");
    el("unlock").disabled = true;
    el("unlock").textContent = "Preparing secure checkout…";
    try {
      const response = await fetch("/api/checkout", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers, version: window.NIJAGame.VERSION })
      });
      const data = await response.json();
      if (!response.ok || !data.url || !/^https:\/\/checkout\.stripe\.com\//.test(data.url)) {
        throw Error(data.error || "Checkout is not available yet.");
      }
      window.location.assign(data.url);
    } catch (error) {
      text("payment-message", error.message || "Payment setup failed. You can still play for free.");
      setPurchaseState();
    }
  }
  function renderReport(result) {
    verifiedReport = result;
    const target = el("report-content"); clear(target);
    const top = node("div", { className: "score-card" });
    const score = node("div", { className: "score-circle" });
    score.append(node("span", {}, String(result.score)), node("small", {}, "/100"));
    const topCopy = node("div");
    topCopy.append(node("h3", {}, result.label), node("p", {}, result.summary));
    top.append(score, topCopy); target.append(top);
    const dimensions = node("div", { className: "report-section" });
    dimensions.append(node("h3", {}, "Your three decision pillars"));
    result.dimensions.forEach(d => {
      const group = node("div", { className: "dimension" });
      const heading = node("div", { className: "dimension-head" });
      heading.append(node("span", {}, d.name), node("strong", {}, d.score + "/100"));
      const track = node("div", { className: "dim-track" });
      const fill = node("span"); fill.style.width = d.score + "%"; track.append(fill);
      group.append(heading, track); dimensions.append(group);
    });
    target.append(dimensions);
    const growth = node("div", { className: "report-section" });
    growth.append(node("h3", {}, "Your next move"),
      node("p", {}, "Strongest area: " + result.strength),
      node("p", {}, "Focus area: " + result.growthArea),
      node("p", {}, result.nextStep));
    target.append(growth);
    const reviews = node("div", { className: "report-section" });
    reviews.append(node("h3", {}, "Your six decisions, explained"));
    result.decisions.forEach((d, i) => {
      const item = node("div", { className: "decision" });
      item.append(node("h4", {}, (i + 1) + ". " + d.title),
        node("div", { className: "points" }, d.points + " / 5 POINTS"),
        node("p", {}, "You chose: " + d.selected),
        node("p", {}, d.feedback),
        node("p", {}, "Lesson: " + d.lesson));
      reviews.append(item);
    });
    target.append(reviews, node("p", { className: "notice" }, result.disclaimer));
    const download = node("button", { className: "secondary", type: "button" }, "Download my report");
    download.addEventListener("click", () => {
      const lines = ["NIJA TRADING IQ — EDUCATIONAL RESULTS", result.score + "/100 — " + result.label, result.summary, "",
        ...result.dimensions.map(d => d.name + ": " + d.score + "/100"), "", "Next step: " + result.nextStep, "",
        ...result.decisions.flatMap(d => [d.title, "Selected: " + d.selected, "Score: " + d.points + "/5", d.feedback, "Lesson: " + d.lesson, ""]),
        result.disclaimer];
      const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = "nija-trading-iq-results.txt";
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    target.append(download);
    show("report");
  }
  async function verifyPayment(sessionId) {
    show("loading");
    try {
      const response = await fetch("/api/results?session_id=" + encodeURIComponent(sessionId), { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.report) throw Error(data.error || "Could not verify this purchase.");
      pendingSessionId = null;
      renderReport(data.report);
    } catch (error) {
      pendingSessionId = sessionId;
      text("free-summary", "Your payment result could not be verified yet. Please retry verification without buying again.");
      text("payment-message", (error.message || "Verification unavailable.") + " Keep your receipt and contact NIJA support if it persists.");
      el("unlock").disabled = false;
      el("unlock").textContent = "Retry report verification";
      show("finish");
    }
  }
  checkCheckout();
  el("start").addEventListener("click", start);
  el("next").addEventListener("click", next);
  el("unlock").addEventListener("click", pay);
  el("replay").addEventListener("click", start);
  el("report-replay").addEventListener("click", start);
  const session = new URLSearchParams(location.search).get("session_id");
  if (session && /^cs_(test|live)_[A-Za-z0-9]{8,}$/.test(session)) verifyPayment(session);
  else if (new URLSearchParams(location.search).get("cancelled") === "1") {
    show("intro");
  }
})();
