// Trading IQ Challenge: fictional market news and a short lesson for every one of the 72 decisions
// (6 scenarios x 12 rounds). All companies, headlines and sources are invented for practice.
// Each entry: [headline, kind, lesson]. kind: "confirmed" | "unverified" | "routine".
// Headlines are shown before the decision; the lesson appears with the feedback after it.
// Nothing here changes any price or any score.

export const NEWS_KINDS = {
  confirmed: { label: "Confirmed report", check: "Check: the original source is named and can be found." },
  unverified: { label: "Unverified claim", check: "Check: no original source is named. Treat it as a rumour until it is confirmed." },
  routine: { label: "Routine update", check: "Check: ordinary scheduled information. It rarely changes the picture on its own." },
};

export const TIQ_NEWS = {
  "Quiet Opening": [
    ["Markets open calmly; traders describe thin activity.", "routine", "Quiet days reward patience. Not every day needs an action."],
    ["Nova Analytics (NVA-1) reaffirms its yearly outlook, no changes.", "confirmed", "News that repeats what is already known seldom moves a price. Do not invent a reason to trade."],
    ["A forum post claims NVA-1 will 'double by Friday'.", "unverified", "Bold promises with no source are a warning sign. Verify before you act, or leave it alone."],
    ["Trading volume stays below its monthly average.", "routine", "Low volume can mean small moves are less meaningful. Avoid over-reading them."],
    ["An industry group publishes a routine monthly sales summary.", "confirmed", "Scheduled data is useful context, but one data point is not a trend."],
    ["Analyst note: 'fairly valued', price target unchanged.", "confirmed", "Opinions differ and can be wrong. Use them as input, not as instructions."],
    ["A social media account says insiders are 'quietly buying'.", "unverified", "Anonymous claims about insiders are easy to invent. Ask where the evidence is."],
    ["Nova Analytics announces a small new office lease.", "routine", "Minor corporate news usually has little effect on price. Keep your plan."],
    ["Broad market index finishes the week slightly higher.", "confirmed", "A rising market does not make every decision good. Judge the process, not the mood."],
    ["Strategist says 'steady drift' likely to continue, but warns of surprises.", "confirmed", "Even a calm trend can change. Know your exit before you need it."],
    ["Short-term traders report 'nothing to do' on quiet tape.", "routine", "Choosing to hold cash or hold a position is an active, valid decision."],
    ["Week ends quietly. Nova Analytics issues no new announcements.", "routine", "Review your decisions: did you act on evidence, or on boredom?"],
  ],
  "Earnings Surprise": [
    ["Quarter Tech (QTR-7) will report earnings later this month.", "routine", "Scheduled events create uncertainty. Decide your position size before the news, not during it."],
    ["Options activity rises ahead of the QTR-7 report.", "routine", "Busy trading before a report shows nervousness, not knowledge of the result."],
    ["Analysts split: some expect a beat, others a miss.", "confirmed", "When experts disagree, nobody knows. Keep any position small."],
    ["A blog claims it 'knows the numbers' from a source.", "unverified", "Leaked-number claims are a classic trap. Real results come from the company filing."],
    ["QTR-7 confirms its report is due tomorrow morning.", "confirmed", "Knowing when news lands helps you plan. Large positions before a report raise your risk."],
    ["QTR-7 reports earnings well above forecasts; early quotes jump.", "confirmed", "Big jumps often partly reverse. Chasing a price after good news is a common mistake."],
    ["Traders debate whether the jump was already 'priced in'.", "routine", "A price can fall on good news if expectations were higher. Wait for the dust to settle."],
    ["CEO says growth will 'continue' but gives no figures.", "confirmed", "Vague statements are not evidence. Look for numbers you can check."],
    ["An unnamed 'insider' says a buyout offer is coming.", "unverified", "Takeover rumours are often false. Never size a trade on an unconfirmed claim."],
    ["Some analysts raise price targets; others warn of a high valuation.", "confirmed", "A single opinion is not a signal. Notice when views conflict."],
    ["Volume falls back toward normal as the excitement fades.", "routine", "Excitement fades. Plans that survive it are the ones set in advance."],
    ["QTR-7 enters a quiet period before its next report.", "routine", "Review: how big was your position when the news arrived, and was that deliberate?"],
  ],
  "Sideways Chop": [
    ["Lock Corp (LKR-3) trades in a narrow range for a third week.", "routine", "In a range, prices bounce. Buying near the top and selling near the bottom is easy to do."],
    ["No major announcements expected for LKR-3 this month.", "confirmed", "No news is a fact too. It can mean waiting is the better decision."],
    ["A chat group says 'LKR-3 is about to break out, get in now'.", "unverified", "Urgency is a pressure tactic. Real opportunities do not vanish in minutes."],
    ["Trading costs on frequent trades add up, says a broker study.", "confirmed", "Every trade has a cost. Many small trades in a range can quietly drain capital."],
    ["LKR-3 touches the middle of its range again.", "routine", "Bouncing prices are not a trend. Avoid forcing a story onto the noise."],
    ["Analyst: 'range-bound until the next catalyst'.", "confirmed", "Without a catalyst, patience is a strategy. Decide what would change your mind."],
    ["A newsletter claims a 'secret pattern' predicts LKR-3 turns.", "unverified", "Patterns that need a secret to work are usually sales pitches. Ask for evidence."],
    ["Market-wide volume is light; many traders are away.", "routine", "Thin markets can mislead. Wait for clearer information."],
    ["LKR-3 tests the top of its range and stalls.", "routine", "Repeated stalls at one level are a clue to review, not a guarantee."],
    ["Analyst repeats: no change to the company's outlook.", "confirmed", "Consistent facts, consistent decisions. Notice if your actions keep flipping."],
    ["LKR-3 slips back toward the middle of the range.", "routine", "Chasing each swing leads to buying high and selling low. Stay with your plan."],
    ["Another week ends with LKR-3 where it started.", "routine", "Review your trade count. Did activity add value, or only cost?"],
  ],
  "Sudden Sell-Off": [
    ["Drax Group (DRX-9) shares drift lower on soft demand.", "routine", "Slow declines are easy to ignore. Check your whole position, not only today's move."],
    ["Credit rating agency places DRX-9 'under review'.", "confirmed", "A review is not a decision. It is a reason to check your limits."],
    ["Rival company reports weaker sales in the same sector.", "confirmed", "Sector news can spill over. Ask how exposed you are to one theme."],
    ["A post says 'DRX-9 is finished, sell everything'.", "unverified", "Panic posts are not analysis. Decide using your plan, not someone's fear."],
    ["DRX-9 drops below a level many traders watched.", "routine", "Broken levels can attract more selling. A stop-loss decides for you in advance."],
    ["Analysts trim DRX-9 targets; none predict a collapse.", "confirmed", "Measured views beat dramatic ones. Look for sources that show their reasoning."],
    ["Short-term traders say selling is 'getting crowded'.", "routine", "Crowds can be wrong both ways. Do not follow a crowd without a reason."],
    ["Company confirms a supplier delay, impact still unclear.", "confirmed", "Uncertain impact means uncertain price. Smaller positions suit uncertainty."],
    ["Breaking: unconfirmed reports of a major problem at DRX-9.", "unverified", "Breaking news is often incomplete or wrong. Before acting on fear, find the original source."],
    ["DRX-9 company statement calls earlier reports 'overstated'.", "confirmed", "Official statements can clarify, but check the details. Prices can stay shaky for days."],
    ["Trading volume stays elevated; moves remain large.", "routine", "After a shock, big moves often continue for a while. Protect capital first."],
    ["Market calms; DRX-9 finishes near its new lower range.", "routine", "Review: did a stop-loss or a plan protect you, or did emotion decide?"],
  ],
  "Breakout Test": [
    ["Horizon Labs (HZN-5) has traded in a range for two months.", "routine", "Ranges end eventually. Waiting for confirmation is not the same as being slow."],
    ["Analysts watch the top of the HZN-5 range for a possible move.", "confirmed", "Many people watching one level can add excitement. It does not guarantee anything."],
    ["Industry conference: HZN-5 demonstration 'well received'.", "confirmed", "Positive reviews are not sales. Look for results you can measure."],
    ["A message board claims a 'guaranteed breakout' on HZN-5.", "unverified", "Nobody can guarantee a market move. Guarantees are a red flag."],
    ["HZN-5 pushes above its range on brisk trading.", "confirmed", "A breakout may be real or a false start. One day is not confirmation."],
    ["The price slips back toward the old range.", "routine", "Breakouts that fade quickly are a common trap. A stop-loss limits the cost of being wrong."],
    ["Analyst: 'breakout needs follow-through to count'.", "confirmed", "Confirmation means more than one move. Patience can save money."],
    ["A newsletter says traders who didn't buy 'missed everything'.", "unverified", "Fear of missing out sells subscriptions. There will always be another setup."],
    ["Volume on the breakout was lower than the earlier push.", "routine", "Weak volume can mean weak conviction. Context matters more than one candle."],
    ["HZN-5 struggles to hold above the old range top.", "routine", "Failure at a level is information. Follow your plan, not your hope."],
    ["Company issues no new news; price continues to drift.", "routine", "Without news to support a move, drifting prices can keep drifting."],
    ["Breakout attempt ends. HZN-5 back inside its old range.", "routine", "Review: did you wait for confirmation, or buy the excitement?"],
  ],
  "Volatility Storm": [
    ["Volt Systems (VOL-2) swings widely at the open.", "routine", "Large swings test emotions. A fixed plan matters more than your mood."],
    ["Traders cite 'macro nerves' for the market-wide jitters.", "unverified", "Vague explanations after the fact are guesses. Do not trade on 'reasons' nobody can prove."],
    ["Price moves 4% in a single hour on no company news.", "routine", "Big moves do not always have a cause. Smaller positions help you stay calm."],
    ["Exchange confirms trading remains orderly despite the swings.", "confirmed", "Orderly does not mean safe. Volatile markets can reverse in seconds."],
    ["A viral video says 'sell now or lose everything'.", "unverified", "Fear is designed to make you rush. Pause and check your plan."],
    ["VOL-2 jumps, then gives back most of the gain.", "routine", "Whipsaws punish constant reacting. Fewer, planned decisions often beat many hasty ones."],
    ["Options traders pay record prices for protection.", "confirmed", "High insurance prices mean high uncertainty. Plan for a wide range of outcomes."],
    ["Analyst: 'impossible to call direction in this environment'.", "confirmed", "Honest uncertainty is useful. Sitting in cash is a valid position."],
    ["Another sharp drop, followed by a quick bounce.", "routine", "Selling at the bottom and buying at the top is how emotion costs money."],
    ["A blogger claims to have 'a system that never loses'.", "unverified", "Every trader loses sometimes. Claims of perfection are a warning."],
    ["Volatility index eases slightly from its peak.", "confirmed", "Calmer markets may return slowly. Do not assume the storm is over."],
    ["Session closes. VOL-2 ends near where it started, after big swings.", "routine", "Review: how many trades did you make, and did each follow a plan?"],
  ],
  // Today's Challenge rotation only
  "Rate Cut Rally": [
    ["Central bank meets next week; borrowing costs are in focus.", "routine", "Scheduled events create uncertainty. Plan your size before the news."],
    ["Economists expect a small rate cut, but are not certain.", "confirmed", "Expectations are already in prices. Surprises move markets, not forecasts."],
    ["A chat room claims the bank 'will cut by a full point'.", "unverified", "Specific claims with no source are guesses. Check the official statement."],
    ["Central bank cuts rates; Abacus Co (ABC-4) jumps at the open.", "confirmed", "Rallies from one event can fade. Decide your exit before you enter."],
    ["Analysts debate how long the rally can last.", "routine", "Debate means uncertainty. Smaller positions suit uncertainty."],
    ["Bank governor says more cuts are 'not guaranteed'.", "confirmed", "Read the exact words. Hope is not a plan."],
    ["A newsletter says it is 'the last chance to buy'.", "unverified", "False urgency pushes people into mistakes. There is always another chance."],
    ["ABC-4 volume cools after the first excitement.", "routine", "Cooling volume can mean the crowd has moved on."],
    ["Sector report: borrowing costs still above last year.", "confirmed", "Context matters. One cut does not erase a year of pressure."],
    ["ABC-4 trades sideways near its recent high.", "routine", "Sideways after a rally can go either way. Wait for confirmation."],
    ["Traders say 'the easy money is made'.", "unverified", "Slogans are not analysis. Look at your own plan."],
    ["Week ends. ABC-4 holds most of its gain.", "routine", "Review: did you chase the jump or follow a plan?"],
  ],
  "Slow Bleed": [
    ["Slow Corp (SLW-8) edges lower on a quiet day.", "routine", "Small losses add up. Check your whole position, not only today."],
    ["Company says demand is 'stable' without figures.", "confirmed", "Statements with no numbers are hard to test. Look for data."],
    ["A post says 'it always bounces back'.", "unverified", "'Always' is not evidence. Ask for the history behind the claim."],
    ["SLW-8 makes another small new low.", "routine", "Steady declines can feel harmless. A stop-loss makes the limit explicit."],
    ["Analyst trims SLW-8 estimates slightly.", "confirmed", "Small downgrades add up like small losses."],
    ["No news from SLW-8; price keeps drifting down.", "routine", "Silence is not good news. Drift needs a reason to reverse."],
    ["A forum says SLW-8 is 'cheap now'.", "unverified", "Cheaper is not the same as good value. Check why it is falling."],
    ["Sector peers also edge lower.", "confirmed", "Shared weakness can point to a bigger cause than one company."],
    ["SLW-8 bounces briefly, then fades again.", "routine", "A short bounce within a decline is not a recovery."],
    ["Company schedules a routine investor call.", "routine", "Scheduled calls can surprise either way. Keep sizes modest."],
    ["Volume stays low; SLW-8 slips again.", "routine", "Low volume decline is quiet, but still costs real capital."],
    ["Month ends with SLW-8 well below its start.", "routine", "Review: when did you decide to act, and what was your plan?"],
  ],
  "Double Top Trap": [
    ["Top Inc (TOP-6) trades near its recent high.", "routine", "Highs are where people feel safest, and often where risk is highest."],
    ["Analysts say TOP-6 is 'testing resistance'.", "confirmed", "Testing a level does not mean breaking it."],
    ["A newsletter says 'TOP-6 will smash through'.", "unverified", "Certainty about the future is a warning sign."],
    ["TOP-6 trades quietly; volume is average.", "routine", "Average volume gives no strong signal."],
    ["Industry data shows steady, not rising, demand.", "confirmed", "Steady is not growth. Match your expectations to the data."],
    ["TOP-6 slips from the high and recovers a little.", "routine", "Small recoveries do not prove direction."],
    ["TOP-6 pushes to a second high on thin volume.", "routine", "A second try at the same price on weak volume can signal weakness."],
    ["TOP-6 fails to hold the high.", "routine", "Repeated failure at one level is information. Follow your plan."],
    ["A chat says 'buy the dip, it always returns'.", "unverified", "'Always' is a red flag. Dips can keep dipping."],
    ["Analyst: 'a double top often leads to a pullback'.", "confirmed", "Patterns are odds, not certainties. Size your risk accordingly."],
    ["TOP-6 drifts lower on light trading.", "routine", "Drift can continue without any news."],
    ["TOP-6 ends the period below its highs.", "routine", "Review: did you follow your plan or your hope?"],
  ],
};

export function newsFor(scenarioName, roundIndex) {
  const list = TIQ_NEWS[scenarioName];
  if (!list) return null;
  const e = list[roundIndex];
  if (!e) return null;
  return { headline: e[0], kind: e[1], lesson: e[2], ...NEWS_KINDS[e[1]] };
}
