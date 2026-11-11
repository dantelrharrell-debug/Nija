# Trading IQ free game — launch verification (9 Nov 2026) — preview only, NOT published

Decision: NOT READY (browser and real-device checks cannot be run from the editor).

## Verified from code and automated tests
- Plays with no sign-in, payment or backend: the game files contain no network calls and no data-store import (launch_guard_test).
- Scores use process only; no return, profit or final value enters Trading IQ (tiq_scoring_test, tiq_engine_test).
- $1 report: "Adults 18+ Only — $1 — Coming Soon"; re-open disabled; sample report only on preview hosts, never on nijaaitrading.com.
- No brokerage, orders, payment keys or checkout links in the game files.
- Progress saving fails safely when the browser blocks storage (saving_safety_test, progress_test).
- Layout rules exist for 640 px and 360 px, horizontal overflow is clipped, tables scroll inside their own box, reduced-motion rules exist, focus outlines and labels exist.
- Eagle mark (BrandMark) in game header; site Academy menu is present on this route.

## NOT verified (needs a person with real devices)
- Visual layout at 320, 375, 390, 768, 1280 px; iPhone Safari, Android Chrome, iPad, desktop browsers.
- Keyboard walk-through of all 12 rounds and Lab modules; screen reader (VoiceOver, TalkBack, NVDA).
- Private-mode / blocked-storage behaviour in a real browser; reduced-motion in a real browser.
- A full human play-through, including achievements and replay.

## Backup and rollback
- Tag `rollback-pre-tiq-launch-20261109` (commit f2ebd273). Bundle of the whole repository and an archive of the built site were made; checksums in backup_20261109/SHA256SUMS (verified; bundle verified OK).
- Prior version for rollback: tag above, or `cdeb27bb`. Rollback = restore that version in the preview, then the owner republishes.
- The bundle/archive copies sit in offline_tiq_backups/ (permissions 700/600, not committed).
