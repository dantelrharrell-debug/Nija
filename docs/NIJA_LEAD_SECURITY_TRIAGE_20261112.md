# NIJA lead-delivery security triage — review only

**Certification status: BLOCKED.** This diagnostic and its tests do not change security baselines, pre-commit hooks, security workflows, runtime configuration, production data, payment settings, consent, dispatch, trading, deployment or provider credentials. Related P0: [#3421](https://github.com/dantelrharrell-debug/Nija/issues/3421).

## Exact GitHub evidence — November 12, 2026

- Merged [PR #3831](https://github.com/dantelrharrell-debug/Nija/pull/3831) hardens read-only SQLite preflight (WAL/SHM/journal checks, alias schema, environment override precedence). The dedicated [CRM run 43301353301](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353301) succeeded, including the 18-case storage suite, 99 CRM regression tests, and offline IONOS checks.
- The mandatory [Security run 43301353484](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353484) **failed**. Pre-commit reported 'hook_modified_files' and 'source_diff_emitted'; full-file baseline-aware secret scan reported 'unbaselined_candidates'. Bandit and dependency scanning jobs passed, as did Gitleaks and TruffleHog PR-diff scans.
- The value-redacted GitHub artifact 'secret-scan-report' (artifact ID 13982201709) has **154 candidates across 89 paths**: 24 Private Key, 15 Basic Auth Credentials, 7 Base64 High Entropy String, 2 Hex High Entropy String, and 106 Secret Keyword. There are 39 higher-priority private-key/basic-auth coordinates across 33 paths.
- **None** of the 154 findings matched the three changed paths in PR #3831: docs/NIJA_LEAD_STORAGE_RECOVERY_GATE_20261112.md, scripts/verify_nija_lead_storage_readonly.py, tests/test_verify_nija_lead_storage_readonly.py. This does not establish that historical findings are benign or permit a full-file scan bypass.
- The artifact belongs to GitHub PR test-merge commit 97c35a7cfb2ba703a317c84327367b83931848df, not every future revision.

## Approval-ready next actions

1. **Independent security review:** Triage 39 high-priority path/line/type coordinates privately. Identify actual credentials versus provably synthetic examples without copying values into issues or the dashboard. Confirmed exposures require separately approved credential rotation and incident handling.
2. **Remaining 115 candidates:** Individually or by independently verified shared patterns adjudicate findings. Never automatically approve entire classes of documentation, test fixtures, or historical code.
3. **Pre-commit failures:** Inspect retained hook/source-diff evidence; prepare narrow, reviewed fixes. Do not disable hooks, auto-baseline findings, ignore failing checks, or silently commit hook modifications.
4. **Rerun hosted checks:** Obtain mandatory security, CRM, CI and other required workflow success on the exact proposed release SHA, with independent review.
5. **Separate live certification:** Verify effective Render lead DB paths and historical data, consistent immutable off-host backups and isolated restore, IONOS published bundle and protected hook ownership, consent preservation, provider idempotency, and Zapier/Apollo/Resend acknowledgments. Lead-only release and new nonmarketing LIVE QA require separate explicit approvals.

## Offline usage

Feed only the existing value-free report created by scripts/run_baseline_secret_scan.py, not a raw credential-bearing scan. Supply a newline-delimited list of exact changed paths.

~~~sh
python scripts/triage_lead_security_report_readonly.py \
  --report /SAFE/secret-scan-report.json \
  --changed-paths /SAFE/changed-files.txt \
  --output /SAFE/triage.json
python -m unittest discover -s tests -p 'test_triage_lead_security_report_readonly.py' -v
~~~

The triage tool emits high-priority path, line, detector metadata, aggregate counts, and scanner status. It returns exit code 1 when the source scan failed and 2 for invalid inputs, never certifies production, never modifies .secrets.baseline and never makes provider calls.

**Decision: HOLD.** Preserve existing QA, pending and uncertain forwarded events, disputed applications, consent, payments, and trading controls. No replay, notification, reassociation, deployment, or production dispatch activation.
