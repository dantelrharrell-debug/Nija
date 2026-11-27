# v515 educational report copy revision — review candidate

Two legacy recommendation labels in `tiq_report.mjs` prevented the repository's compliance preflight from passing. This candidate changes those labels to **Advanced Investing and Income Planning**. Recommendation IDs, links, game decisions, scoring formulas, and the engine are unchanged.

This is a derived source revision requiring review. It is not a claim that the revised bytes came from the original approved archive. The original archive checksum remains provenance; the pinned report-module checksum and the 56-file source manifest now describe this candidate. Every source-file hash is still checked, and report-module tampering remains rejected.

The backend manifest adds a report digest and the `-copy1` version suffix. Its identity deliberately differs from the original manifest. Existing runs cannot silently reopen under the revised manifest. Do not migrate entitlements, replace an installed manifest pin, or ask a purchaser to pay again as part of this change. Compatibility and recovery need review in an isolated preview before any deployment.

## Validation

- Compliance preflight passes locally.
- Ten backend v515 tests pass, including old-manifest rejection, report-source tampering, scoring, purchaser ownership, and refunded/disputed entitlement rejection.
- Nine standalone source-integrity and payment-boundary tests pass.
- All fourteen original offline test suites pass.
- Twenty-four deterministic original-versus-revised report and HTML comparisons pass after normalizing only the two lesson labels. Fixtures span both modes and all three levels; standard-mode day numbers remain zero.

The exact source checksum is stored in the source manifest and backend adapter. The baseline changes only the existing public checksum identity corresponding to that source-manifest entry; no credential candidate is reclassified.

This change leaves free gameplay, the separate course, payment activation defaults, and trading controls unchanged. It does not install a Kraken collector or certify account identity, ledger reconciliation, protective exits, or production readiness. Hosted mandatory checks, independent review, backup/restore proof, and exact-release approval remain required before deployment. Local results do not substitute for these gates.
