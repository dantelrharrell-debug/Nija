# Owner-aligned adaptive intelligence policy
Status: proposed engineering acceptance policy; not production certification or order authorization.
Owner directive recorded 2026-11-25: learn from owner decisions, independently improve production reliability and pursue sustainable net profitability over losses.

## Authority
Owner preferences are versioned, attributable, scoped and revocable. Inferred preferences are proposals, not permissions. Never persist credentials or unnecessary personal data. Existing risk limits, order authorization, kill switches, account boundaries and release controls take precedence. No live orders or capital changes are authorized by this policy.

## Reuse first
Audit core/self_learning_engine.py, bot/adaptive_profit_exit_v74_patch.py, bot/mmin/transfer_learning.py, bot/dashboard_server.py, bot/profit_optimization_config.py and docs/WEBSITE_PROFIT_REPORTING_API.md before adding components. Establish actual callers, persistence, account isolation, tests and deployed versions. Do not assume source presence proves runtime readiness.

## Learning evidence
Use reconciled, deduplicated, same-account execution records with opening-lot and durable intent links, fees, slippage and provenance. Quarantine incomplete or stale records. Never synthesize missing historical evidence. Keep training and evaluation datasets separate and time ordered. Evaluate candidate models offline or in paper trading; compare against frozen baseline after costs, drawdown, uncertainty, regime changes and stress scenarios. No automatic promotion to live execution. No learning may weaken protective controls.

## Business and production
Track verified net operating profit, revenue, refunds, expenses and consent-compliant unique visitors; target at least USD 1 net operating profit per verified visitor, not a guaranteed outcome. Monitor service health, security checks, dependency drift and data freshness. Repair in isolated branches with regression tests, rollback and readback. Do not purchase resources or alter billing without scoped authorization.

## Acceptance sequence
1. Inventory existing modules and runtime wiring.
2. Define owner decision records with provenance, effective scope, revision and supersession.
3. Verify durable learning data and recovery, including account isolation and duplicate rejection.
4. Validate offline candidate evaluation and negative tests for missing evidence, leakage and unsafe promotion.
5. Integrate read-only health and business metrics with existing dashboard.
6. Verify CI, isolated deployment and rollback; report exact evidence and remaining blockers.
7. Require existing production release gates and separate explicit live-order authorization before any execution change.

Record each experiment, baseline, dataset version, result, rejection reason and approval status. Missing evidence is a blocker, not a passing result.
