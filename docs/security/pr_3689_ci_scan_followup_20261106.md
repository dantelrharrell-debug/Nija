# PR #3689 post-merge security workflow diagnosis (2026-11-06)

## Scope and exact source evidence

PR [#3689](https://github.com/dantelrharrell-debug/Nija/pull/3689) merged
into \`main\` at 2026-11-06 16:51:15 UTC as
\`b07d6b0615139c56e5afa778a3012087fcda3bee\`.
The original head was \`3f8b2dad0cf5d715d9a4c81da220ff07783e8c67\`.
Its separate SQLite persistence fail-closed handler and synthetic HTTP 503/no-forwarding
regression are retained unchanged.

The original [Security Scanning run 42253875317](https://github.com/dantelrharrell-debug/Nija/actions/runs/42253875317),
Secret Scanning job **128015736671**, exited 1 at baseline-aware
\`detect-secrets\` enforcement. The pinned 1.5.0 wrapper completed, reported
\`unbaselined_candidates\`, and emitted a sanitized artifact
**13522845088**. No scanner crash or new PR-specific finding was demonstrated.
Gitleaks' pinned PR diff and TruffleHog's verified-only PR scan both passed.
The dependency, Bandit and high-level pre-commit jobs were green; the pre-commit
job's own run step was **not** successful (see below).

## Sanitized comparison to prior failure

Compared the structured path/line/type triples from the two **value-free**
\`secret-scan-report.json\` artifacts, not credential contents:

| Evidence | Prior run 42167623969 (artifact 13480096252) | PR #3689 run 42253875317 (artifact 13522845088) |
| --- | ---: | ---: |
| Tracked files | 3,821 | 3,828 |
| Unbaselined locations | 270 | 268 |
| Shared exact path/line/type locations | 268 | 268 |
| New locations | — | **0** |
| Baseline would change | false | false |
| Exit | 1 | 1 |

The two locations absent in the later report were in
\`tests/test_nija_game_hosted.py\`; neither was in PR #3689's two changed files.
The 268 current detector classifications are **209 Secret Keyword**, **30
Basic Auth Credentials**, **23 Private Key**, and **6 Base64 High Entropy
String**. This proves no newly *reported* candidates in #3689; it is **not**
proof that all remaining 268 are false positives or that no secret exists.

The committed baseline pins detect-secrets 1.5.0. Its known identities remain
reviewed, and full tracked-file enforcement remains blocking. Do not generate
a broad new baseline, skip historical findings, change allowlists, silence
error codes, or put credential values/hashes into CI artifacts or tickets.

## Additional CI visibility failure

Pre-commit job **128015736961** in the same run showed
\`pre-commit run --all-files --show-diff-on-failure\` **exit code 3**.
Go hook initialization failed while building pinned dependencies:

\`\`\`text
golang.org/x/tools@v0.16.0/internal/tokeninternal/tokeninternal.go:
invalid array length -delta * delta (constant -256 of type int64)
\`\`\`

This is an old \`golang.org/x/tools\`/Go toolchain compatibility failure,
not a successful pre-commit check. The workflow's
\`continue-on-error: true\` hid that failure at job level; its report said
"validation complete" rather than reporting the step outcome.

The narrowly scoped follow-up removes \`continue-on-error\` so every hook
failure blocks CI, isolates a compatible Go 1.24.x toolchain for these existing
hooks (without changing runtime Go or trading dependencies), and emits the
actual pre-commit outcome in the report. It adds workflow-regression assertions
to the existing pinned detect-secrets test suite to prevent either enforcement
gate from being silently weakened. Go 1.24.x compatibility must be confirmed
by exact-head hosted CI; a later independently reviewed hook/toolchain upgrade
is preferable to relying indefinitely on an older Go line.

## Tested evidence from the PR-head workflows

- Security run 42253875317: **5 pinned baseline wrapper tests passed**;
  Gitleaks PR-diff passed; TruffleHog PR passed; detect-secrets tracked-file
  enforcement failed as expected on 268 unreviewed candidates.
- Lead/CRM recovery run 42253875315: **86 passed**.
- CI run 42253875389: **55 commissioning tests + 75 subtests passed**,
  and **1,035 fail-closed tests + 658 subtests passed**; the documented
  repository CI baseline-ratchet reported no unexpected failures
  (\`CI_BASELINE_RATCHET_PASSED tests=2917 known=96 resolved=90 unexpected=0\`).
  This is not a blanket all-tests-clean claim.
- Artifact scanning run 42253875490 still has independent GuardDog and
  Trivy/Grype failures. They are not attributable to the lead handler
  without separate evidence, nor resolved by this PR.

## Unresolved requirements and safety boundary

1. Authorized security reviewer privately classifies each unreviewed
   location, prioritizing 23 Private Key and 30 Basic Auth classifications;
   rotate/revoke **confirmed genuine** exposed secrets, investigate access
   and relevant history, and then only review narrowly justified baseline
   identities. No values should be posted to GitHub.
2. Let exact-head GitHub CI execute the pre-commit hook suite with corrected
   toolchain. Any hook-level findings remain failing, now visibly.
3. Independently triage container and package-supply-chain findings from the
   artifact workflow; no vulnerability gate was disabled here.
4. **Issue #3421 stays open/not certified** until authenticated IONOS LIVE
   storage/admin proof, published form routing, original Zapier account/Zap
   eligibility and activation, consent-preserving authorized single QA
   end-to-end test, and exact Apollo receipts are demonstrated.

No production deploy, IONOS form submissions, customer replay, outbound
forwarding, CRM modifications, payments, trading-order actions, broker
authorization, or secret-baseline change was made.
