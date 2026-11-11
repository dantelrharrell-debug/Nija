# NIJA AI Education Pilot — offline mock only

**Status:** Source merged into main by PR #3744; not production-certified or activated. The separate hardening changes are review-only on a fix/ branch and must not be merged or deployed without explicit authorization.

## Source and isolation
Based on reviewed curriculum in `education_system.py` (lesson_001, lesson_002, lesson_003, lesson_005). This package does not import the Flask module, register an HTTP endpoint, access a database, or connect to external AI, broker, payment, customer account, or trading services. The provider returns static educational examples, not generative AI.

## Offline test
From repository root, with Python 3:

```sh
python -m unittest discover -s education_pilot/tests -v
```

Tests use only the Python standard library, synthetic inputs, and no credentials or network. Independently verify tests and security scanning before approving any integration; runner-startup failures are not successful test runs.

## Limits and safety
Input screening is intentionally incomplete and is **not** production data-loss prevention. Do not submit real personal information, brokerage details, credentials, private customer prompts, or financial data. The in-memory request counter is per Tutor instance, not a persistent, distributed, billing-enforced limit. It cannot prevent external costs. The mock-only response schema is checked, but this is not a substitute for production security review.

## Render diagnosis (November 11, 2026)
Render service `srv-d3qtoogdl3ps73c7ovog` failed to build merge commit `44ea9de` while installing existing Python dependencies. Logs show pandas Cython compilation under Python 3.13 failing because NumPy headers require Cython 3 or newer. The education pilot does not add dependencies. The failure is not evidence that the pilot was activated. Correcting Render, Python, requirements, or production configuration is outside this PR's authorization.

## Before any integration
Obtain separate explicit approval. Verify any API credits, organization ownership, model pricing, vendor data handling and retention. Review `mobile/DATA_INVENTORY.md`, privacy disclosures, processor inventory, and consent requirements. A future separately reviewed provider adapter would need server-side credentials, enforceable budgets, timeouts, and privacy safeguards. Do not enable AI API calls, production endpoints, customer data collection, payments, or trading.

## Acceptance
Review this branch against main; run the offline tests independently; inspect security scanning; do not merge, deploy, publish, activate payments or trading.
