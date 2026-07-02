## Owner

- Primary owner: <!-- @username -->
- Backup owner: <!-- @username (optional) -->

## Purpose

Describe what problem this PR solves and why it is needed.

## Risk Assessment

- Risk level: <!-- low / medium / high -->
- Impacted areas:
  - <!-- component/module -->
- Key failure modes:
  - <!-- what could go wrong -->

## Rollback Plan

- Revert strategy:
  - <!-- exact rollback approach -->
- Data/state considerations:
  - <!-- migrations, toggles, caches, etc. -->

## Validation

- [ ] Local checks passed
- [ ] CI checks passed
- [ ] Monitoring/observability impact reviewed

### NIJA Safety Checks

- [ ] `python -m py_compile` clean on all changed `.py` files
- [ ] No bypass flags committed (FORCE_TRADE, NIJA_FORCE_ACTIVATION, NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK, NIJA_DISABLE_WRITER_LOCK, NIJA_SKIP_STARTUP_PHASE_GATE)
- [ ] Authority-gate denials are NOT recorded as exchange order rejections (kill-switch feedback loop invariant preserved)
- [ ] For trading logic changes: strategy change backtested before live deployment
