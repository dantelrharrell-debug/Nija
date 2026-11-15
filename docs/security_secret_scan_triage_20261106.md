# Secret-scanning release gate triage — 2026-11-06

Source: GitHub Actions Security Scanning run 42167623969, job 127727657059, artifact 13480096252 (secret-scan-report). The report intentionally contains paths, line numbers and detector categories only, not secret values.

- Scanner: detect-secrets 1.5.0; 3,821 tracked files; outcome: unbaselined_candidates; exit code 1.
- 270 candidate findings: 210 Secret Keyword, 30 Basic Auth Credentials, 23 Private Key, 7 Base64 High Entropy String.
- Baseline would change: false. Gitleaks PR scan reported no leaks; that does **not** clear the detect-secrets findings.
- Highest-count file: bot/test_platform_account_layer.py (57); scripts/setup_env.py (9); USER_TRADING_ACTIVATION_GUIDE.md (6); bot/nija_deploy_config.py (6); tests/test_kraken_native_runtime_connection.py (6).

## Required remediation

1. Have the authorized security reviewer inspect each value privately, prioritizing 23 Private Key and 30 Basic Auth candidates. Classify real credentials versus synthetic test fixtures and documentation. Do not copy candidate values into tickets, PRs, or logs.
2. Immediately revoke/rotate any real exposed secrets and inspect access logs. Remove exposure from tracked source; assess history cleanup and downstream consumers without rewriting protected history casually.
3. Replace hard-coded synthetic test material with clearly documented inert fixtures where possible; do not weaken scanning or automatically mark all candidates as false positives.
4. Only after review, update the version-pinned baseline through the repository's reviewed workflow and rerun all security scans. Preserve scanner failure until review completes.
5. Separately review artifact scanning failures (Python package and Docker image jobs); they are not cleared by this triage document.

This document is a **read-only finding summary**, not a certification, approval, collector installation, deployment, or authorization to trade.
