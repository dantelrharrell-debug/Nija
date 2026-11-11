# NIJA AI Education Pilot — offline mock only

**Status:** Draft, not production-certified. No external AI service, broker, payment, customer account, database or trading integration.

## Source and isolation
Based on the reviewed curriculum in `education_system.py` (lesson_001, lesson_002, lesson_003, lesson_005). This package does not import that Flask module, avoiding its database dependencies and side effects. It is not registered as an HTTP endpoint. No existing files are changed.

## Test
From repository root, with Python 3:
```sh
python -m unittest discover -s education_pilot/tests -v
```
This uses Python standard library only and does not need credentials or network access. The mock returns static responses and does not claim to provide generative AI.

## Limitations
Input screening is intentionally conservative and incomplete; do not submit actual PII, brokerage details, credentials, private customer prompts or financial data. This prototype is not an effective production DLP system. The budget counter is per process, not a billing-enforced hard cap. It does not prevent charges from unrelated projects.

## Before any API experiment
Obtain new explicit approval. Verify the actual credit grant, Personal organization and applicable model pricing. Review vendor data handling and retention, update `mobile/DATA_INVENTORY.md`, privacy disclosures, processor inventory and applicable consent before customer data is ever used. Add a separately reviewed provider adapter with server-side credentials, enforced budgets, timeouts and privacy protections. Do not activate mobile or production endpoints.

## Acceptance
Review diff and branch against main; execute offline tests independently; inspect security scanning; treat runner-startup failures as infrastructure failures, not passing tests. Do not merge, deploy, publish, collect customer data, enable payments or activate trading.
