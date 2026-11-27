# Kraken shadow outcome admission (offline review only)

A full-close callback can currently notify the adaptive threshold controller,
weight tuner and regime calibrator without proving which account and opening
lot produced that outcome. Replaying the callback can count it twice. Treat this
as a source-level finding, not evidence of a live impact.

The proposed SQLite inbox is account-scoped, persistent, and append-only for
new evidence identities. Exact logical replays are no-ops even if the evidence
digest or fill order changes. Conflicting claims and cross-lot fill reuse are
quarantined, including any previously accepted affected lot. Reports rebuild
from a scoped snapshot instead of replaying into an existing learner. It uses
an independent offline database; do not point it at a broker journal, reuse an
old learning state file, or enable adaptive selection.

## What this does not prove

- A terminal order status and its evidence hashes do not prove an opening-lot
  link, complete allocation of partial fills, or fee-adjusted whole-lot return.
  The production terminal verifier and durable submission journal cannot be
  used as the sole reader for this inbox.
- The reader contract requires a reviewed same-account causal link from the
  opening intent to order and lot, plus all independently reconciled closing
  fills, quantities and fees. The inbox validates shape and scope, not the
  truth of arbitrary caller assertions. The tests supply fixtures, not broker
  or production evidence.
- The retained 13 historical closes lack verified local opening-lot links.
  Keep them excluded. This review does not initialize any production journal.
- No live execution callback, learner, Kraken reader, or startup file is
  changed. Production wiring requires an independently reviewed reader and
  decisions on lot identity and split-fill allocation. This version
  quarantines a fill claimed by multiple lots rather than guessing allocations.

Run from the repository root:
`python -m unittest discover -s tests -p test_kraken_shadow_outcomes.py -v`.
