# Trading IQ free game — manual test checklist (NOT YET RUN — every box is open)

Where: the editor preview, page /trading-iq-challenge. Do not publish while testing.
Record for each row: tester, device, browser + version, date, PASS/FAIL, screenshot name.

## A. Layout (no sideways scrolling, nothing clipped or overlapping, buttons reachable)
Widths: 320, 375, 390, 768, 1280 px (browser dev tools device mode, then one real phone and one tablet).
Screens at each width: [ ] start/welcome  [ ] a round with chart  [ ] feedback after a round  [ ] challenge summary
[ ] final results + report card  [ ] progress/badges panel  [ ] each Practice Lab tab (Scenarios, Allocation, News, Risk, Discipline)  [ ] tables inside Lab/report
Pass rule: page never scrolls sideways; text readable without zoom; every button at least ~44 px tall.

## B. Full play-through
[ ] Beginner: all 12 rounds of one challenge, then all six challenges
[ ] Intermediate and Advanced each started once
[ ] Buy / Sell / Hold and the stop-loss tick all respond
[ ] Replay a challenge; "beat your best" only compares current-method runs
[ ] Each Practice Lab module completed with right and wrong answers; Lab score shows; "Not scored" diversification case checked
[ ] Achievements unlock once, not twice
[ ] Check by eye: two runs with the same decisions show the same Trading IQ whatever the price path/portfolio value

## C. Progress saving
[ ] Reload mid-challenge: resume offered and correct
[ ] Reset progress asks for confirmation
[ ] Private/incognito window and a browser with site data blocked: game still plays, "cannot be saved" notice shows
[ ] Lab "save answers" off by default; on = saved note; clearing works

## D. Keyboard only (Tab, Shift+Tab, Space, Enter, arrows)
[ ] Every control reachable in a sensible order; visible gold focus outline
[ ] Decision buttons, stop-loss tick, level buttons, Lab tabs and radio groups operable
[ ] After a decision, focus/feedback is announced; no keyboard trap

## E. Screen reader (VoiceOver iOS/macOS, TalkBack, NVDA)
[ ] Headings and landmarks make sense; chart has a text title
[ ] Feedback after each round is spoken; progress bars have names
[ ] Lab answer feedback is spoken; form fields have labels

## F. Reduced motion
[ ] OS "reduce motion" on: no entrance animation, chart drawing or bar transitions

## G. Safety checks
[ ] No sign-in, payment or signup prompt anywhere in the game
[ ] "Adults 18+ Only — $1 — Coming Soon" visible; no buy button; sample report appears only in preview
[ ] Eagle mark in header; Academy menu works from this page
[ ] Browser network panel shows no requests to payment, brokerage or data services while playing

## Evidence to attach
Screenshots per width, short screen recording of one full challenge, device/browser list, and this sheet filled in.
Automated evidence already collected: see LAUNCH_VERIFICATION_20261109.md (all suites 0 failures) and offline_tiq_tests/launch_guard_test.mjs.
