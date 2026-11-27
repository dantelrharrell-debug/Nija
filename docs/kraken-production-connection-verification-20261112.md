# Kraken production connection verification — November 12, 2026

**NOT CONNECTED — SPECIFIC BLOCKERS REMAIN**

Checked November 12, 2026, approximately 1:08–1:16 PM Pacific (21:08–21:16 UTC).
This is an authenticated read-only production inspection plus a release-test repair.
It is not installation, independent certification, deployment approval or trading authorization.

## Implementation and release alignment

Production service: `srv-d98dsr5aeets73fpbaqg`, workspace
`tea-d37fhe8gjchc73c8eo0g`. Auto-deploy is off.
Live deploy: `dep-dbqth6jbc2fs73fcd2vg`; production commit:
`632405228ff2dabb053eecf7dacc35db9325a454`.
Inspected protected release head: `e429d609f61d77512025b8bc9b1b829572120eb1`.
Neither the production image digest nor an approved replacement digest was verified.

PR #3820 adds native kill-switch/position-sync construction. PR #3832, now merged
to the release branch, adds construction of the actual four other native readers.
PRs #3827 and #3830 landed on main, not this release branch. The requested command
`python -m unittest tests.test_kraken_source_startup_contract_review -v` failed on
the unmodified release with ModuleNotFoundError. This candidate restores that test
to the protected release, adds a same-function registration-before-install check
and rejects an exec/subprocess handoff between those calls. Both general CI and
the collector workflow explicitly execute it; collector path filters include it.

Changed files:

- `tests/test_kraken_source_startup_contract_review.py`
- `.github/workflows/ci.yml`
- `.github/workflows/kraken-collector-v487.yml`
- This report.

No runtime implementation, protected file, environment variable, order policy,
ledger record, Redis state, signature, broker account or release branch was changed.
No merge, deployment, restart or live-order submission was performed.

## Actual production interpreter and protected artifacts

Authenticated Render Shell inspection established:

- Canonical process PID 255; executable `/usr/local/bin/python3.11`;
  argv `/usr/local/bin/python3 -u scripts/canonical_runtime_launcher_v26.py`;
  working directory `/app`.
- Protected bootstrap AST contains `os.execvpe` at line 231 and no startup
  registration call. Its confidential source was not published.
- Neither `/etc/secrets/.render-kraken-startup-root.py` nor
  `/etc/secrets/.render-kraken-startup-binding.json` exists in the secret mount.
- The live image lacks `bot/kraken_protected_startup_root.py` and
  `bot/kraken_native_four_source_binding.py`.
- Live `bot_main.py` calls `install_from_canonical_startup` at line 1474 and
  `start_trading_engine` at line 1509, without `register_from_protected_root`.
- The reviewed release source already calls the fixed-path protected-root loader
  after canonical strategy publication and before the existing atomic installer.
  Launcher/main/module handoffs stay in that final Python process. Registration
  in the outer protected bootstrap before OS exec would still be discarded.

Do not add registration to the old outer bootstrap. The existing final-interpreter
hook needs the reviewed image and genuine protected source/manifest artifacts.
Do not create an always-True reviewer or substitute environment flags.

## Production observations and safety controls

At 21:08 UTC production logged `collector_installed=false`,
`producer_status=collector_missing`, `ready=false`, with these missing fields:

| Required observation | Authenticated collector result |
| --- | --- |
| account_permissions | collector_missing |
| account_identity | collector_missing |
| broker_balances | collector_missing |
| position_ledger_reconciliation | collector_missing |
| protective_exit_readback | collector_missing |
| open_order_reconciliation | collector_missing |
| duplicate_order_fence | collector_missing |
| writer_lease | collector_missing |
| nonce_sequence | collector_missing |
| operator_authorization | collector_missing |
| kill_switch_clear | collector_missing |
| risk_limits | collector_missing |
| position_sync | collector_missing |

**Valid observations: 0/13. Four authoritative production bindings verified: 0/4.**
The latter is a verification count, not proof that every backing service is absent.
No current startup certification could be authenticated through the absent manifest.
Kraken account identity/API-key scope, independent signer identities, provider
registry and release/image pins consequently remain uncertified.

The runtime separately logs `PREACTIVATION_EXECUTION_PROOF_V16 ready=false`,
`producer=missing`, `failing_condition=verification_stale`,
`trading_fail_closed=true`. It does not have fresh execution proof.
At 21:15:29 UTC `STARTUP_READONLY_RECOVERY_DIAGNOSTIC` reports
`state=READ_ONLY_RECOVERY allow_new_orders=false canonical_gate_unchanged=true`.
Observed process configuration preserves `STRICT_REDIS_WRITER_LOCK=true`,
`NIJA_REQUIRE_REDIS_FOR_LIVE=true`, `NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false`,
`FORCE_TRADE=false` and `NIJA_FORCE_ACTIVATION=false`.
The READ_ONLY_RECOVERY environment variable itself is unset; the log establishes
the recovery state. An unset variable must not be confused with runtime state.

An additional 21:15:26 UTC log reports ETH-USD exit market-price unavailability,
`exit_not_submitted=true`, `synthetic_price=false`, `fail_closed=true`.
This is a separate protection/readiness concern, not an exchange rejection or
proof that the independent protective-exit certification passed.

## Four authoritative dependencies: current versus required

| Family | Current authoritative finding | Exact corrective action |
| --- | --- | --- |
| Ledger | Runtime selects `/data/trade_ledger.db`. Read-only SQLite schema inspection finds trade_ledger, open_positions and pending_kraken_closes, but lacks ledger_open_orders and ledger_evidence_state. trade_ledger and open_positions each lack broker, account_scope, api_key_sha256 and account_sha256. | Implement and independently review a separate durable provenance-preserving ledger import/publisher. Reconstruct account/key-attributed fills, fees, lots, open orders and protective exchange IDs from authenticated complete history. Verify cursor exhaustion, inventory reconciliation and backup/restore. Never relabel the current rows or merely create empty tables. Bind that reviewed source with make_kraken_ledger_evidence_provider. |
| Redis | No protected resolver binds an authenticated complete durable inventory, cutover coverage verifier or scope observer. Existing writer/nonce environment guards are enabled; that is not inventory certification. | Review and instrument every submission/retry route and historical boundary under existing writer authority; reconcile durable unresolved intents; supply independently authenticated coverage, source-binding/deployment pins and read-only client to RedisEvidenceReader.collect. Validate lease, nonce lineage, fence freshness and complete inventory. Do not infer completeness from ping, SCAN, TTL fences or an empty set. |
| Operator | No protected startup manifest/source provisions the independently reviewed operator/status roots and current records. General signed authorization and revocation status were not verified. | Establish legitimate operator-signing and separate status/revocation authority; privately provision pinned public roots and an uncached signed-record reader. Authenticate exact account/key/release/mode/scope and current active status. No signatures or general-live authorization may be invented from this repair request. |
| Risk | No protected resolver connects a reviewed atomic account-risk publisher. Current authenticated capital/exposure/policy source records were not verified. | Implement or identify the authoritative account-scoped producer, covering capital, all positions and pending/reserved intents, policy revision and original timestamps. Independently review source identities and monotonic revisions; bind make_kraken_risk_limits_provider. Global governor health alone is insufficient. |

The separate certified-ledger path, Redis cutover implementation and risk/status
publisher identities cannot be guessed from these schemas. Actual producer review
and data access are necessary before a production resolver is safe to provision.
This inspection did not connect to Kraken from a second interpreter, take over a
nonce owner, scan private records or mutate the operational ledger.

## Local and hosted validation

Local Python 3.12, isolated startup hooks:

- Requested unittest suite: **6 passed**, after the release repair.
- Signed/protected/canonical startup, native four/pair, ledger, Redis, operator,
  risk and kill-switch/position-sync suites: **431 passed, 7 skipped**.
  Seven skips require a local Redis Server, unavailable here.
- Collector connection/bridge/composition, read-only ledger preflight/history gap,
  four-family composition and execution-admission acceptance: **65 passed**.
- Protected-bootstrap structure audit: **6 passed**.
- Total across those disjoint selections: **508 passed, 7 skipped**.
- Changed Python compilation, workflow YAML parsing, git diff checks,
  detect-secrets 1.5 changed-file hook against the unchanged baseline and
  Bandit medium/high checks passed.
- Repository-requested runtime-tools-secret_scanning and codeql_checker tools
  are unavailable; do not describe the local alternatives as those exact tools.
- Local Docker and real Redis/container execution are not claimed.

Hosted checks were independently fetched for exact release commit e429d609:

| Workflow | Observed result | Evidence |
| --- | --- | --- |
| Kraken collector regression | success | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305918882 |
| Render recovery regression | success | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305919286 |
| CI | success | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305918732 |
| CodeQL | success | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305918972 |
| Image build | success | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305919162 |
| Security Scanning | failure | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305919345 |
| Artifact Scanning | failure | https://github.com/dantelrharrell-debug/Nija/actions/runs/43305919011 |

Security job 131489076527 reports **154 unbaselined candidates**; the baseline
enforcement regression tests passed (111), but enforcement failed. Pre-commit job
131489076984 fails bandit, check-docstring-first, detect-private-key, detect-secrets,
end-of-file-fixer, gitleaks, name-tests-test and trailing-whitespace. Dependency
vulnerability scan and dedicated Bandit job pass. Artifact jobs fail image
Trivy/Grype and PyPI Guardian package analysis. Findings require actual
classification/remediation and applicable credential rotation verification;
no baseline expansion, finding waiver or gate removal is authorized here.
These results predate this candidate; new candidate CI must be reported separately.

## Exact external review/provisioning request — prepared, not sent

To the independently designated technical source reviewer, backup/restore
reviewer and broker/ledger/protective-exit reviewer:

> Review the complete protected Kraken resolver and its transitive dependencies
> for NIJA service srv-d98dsr5aeets73fpbaqg. Confirm the exact proposed release
> commit and immutable image digest, canonical Kraken account and current
> API-key fingerprints, all thirteen distinct provider IDs and actual objects,
> the independent ledger, complete durable Redis inventory and writer/nonce
> lineage, operator/status trust roots, account risk publisher, current stop
> state and position/protective-order reconciliation. Supply auditable source
> ownership and current backup-restore/broker-ledger-exit evidence. Only after
> completing the relevant independent work, return genuine bounded Ed25519
> certifications for independent_review, backup_restore and broker_ledger_exits
> under the existing startup-receipt contract, with independently provisioned
> public trust roots and signer identity/custody. Bind the independent_review
> artifact hash to the exact protected root bytes. Do not include signing keys
> in chat, GitHub or the protected manifest. This request grants no trading
> permission and asks for no live order or safety-control bypass.

Approving authorities: source-code/source-ownership reviewer; actual backup
restore verifier; actual broker/ledger/protective-exit verifier. Their identities,
trusted public keys and artifacts were not established in this session. Dante is
the deployment owner. Owner approval alone cannot replace the required independent
evidence or the separate operator/status signatures. No external party was contacted.

After legitimate sources and certifications exist, prepare the exact two
protected files for private review. Provisioning protected secrets requires its
applicable approval. Once all exact-release security/review/backup gates pass,
obtain owner deployment approval for that exact commit and image. Do not seek
deployment approval for an uncertified, unpinned image now.

## Required rollout and trading separation

1. Establish and review real source producers; complete ledger/history and Redis
   cutover work with durable backup/rollback evidence.
2. Review the final resolver, provider objects, account/key identity, exact image,
   trust roots and all three genuine certification artifacts.
3. Pass mandatory hosted checks on the exact proposed release and image.
4. Privately provision the approved fixed-path protected files; retain the
   existing ledger bootstrap, existing service and auto-deploy-off setting.
5. Deploy only the specifically approved release/image after owner approval.
6. Verify the new final Python interpreter logs
   KRAKEN_PROTECTED_STARTUP_ROOT status=protected_startup_factory_registered,
   then KRAKEN_STARTUP_EVIDENCE status=diagnostic_collector_installed
   authorizes_orders=false. A registration message is not collector certification.
7. Confirm collector_installed=true and 13/13 genuinely valid fresh observations,
   exact scope/provenance, four live bindings and authenticated certifications.
8. Separately establish fresh execution proof and resolve protective-price,
   ledger, kill-switch, risk, nonce and authorization concerns. Do not create a
   new live fill merely to refresh a proof timestamp.
9. Preserve allow_new_orders=false and fail_closed=true. Request separate explicit
   owner live-trading approval only after readiness certification.

Rollback: this candidate changes only tests/workflows/docs and can be reverted
through review. No production state was migrated. Any future source publication,
inventory cutover, protected provisioning or deployment needs its own reviewed
backup/rollback plan; reverting code must not delete production ledger/inventory.

Sources: https://dashboard.render.com/web/srv-d98dsr5aeets73fpbaqg/shell ;
https://dashboard.render.com/web/srv-d98dsr5aeets73fpbaqg/logs ;
https://github.com/dantelrharrell-debug/Nija/issues/3800 ;
https://github.com/dantelrharrell-debug/Nija/pull/3820 ;
https://github.com/dantelrharrell-debug/Nija/pull/3827 ;
https://github.com/dantelrharrell-debug/Nija/pull/3830 ;
https://github.com/dantelrharrell-debug/Nija/pull/3832 .
