# Exact synthetic payment-test candidate review

Review base: main commit `e8f682deab471522c9da6114f7c239e6f8c72f6d`.

Nine `Secret Keyword` identities in six existing test files are deterministic, inert test inputs. The source files are unchanged. Their public source was retrieved at the review-base commit and compared with the local bytes before publishing the baseline change.

| Test source | Reviewed identities | Evidence |
| --- | ---: | --- |
| `game_sandbox/test_v515.py` | 1 | Literal fixture prefix in a temporary test configuration; ProviderFixture implements the provider boundary. |
| `web/trading-challenge/tests/server.test.mjs` | 1 | Explicit non-real test key; Stripe fetch calls are replaced by deterministic local responses. |
| `web/trading-challenge/tests/stripe-webhook-verify.test.mjs` | 1 | Local HMAC input for signature, timestamp, and tampering regressions. |
| `web/trading-challenge/tests/tiq12-upgrade6-security.test.mjs` | 4 | Fixed test configuration and deliberately invalid live-key/signature inputs; rejection assertions remain intact. |
| `web/trading-challenge/tests/tiq12-upgrade6-service.test.mjs` | 1 | Fixed configuration for the synthetic service/provider boundary. |
| `web/trading-challenge/tests/tiq12-upgrade6-stripe.test.mjs` | 1 | Deliberately invalid live-key-shaped input must be rejected before HTTP; other adapter calls inject a fake fetch function. |

The baseline adds only each exact filename, detector type, and captured-value hash. No wildcard, detector removal, path exclusion, credential rotation, runtime configuration change, or trading authorization is included. All prior baseline records and scanner configuration remain unchanged. The public price identifier in `server.test.mjs` is not part of this review.

Validation: all 68 JavaScript scoring/payment-boundary tests pass with an additional socket guard denying non-loopback destinations. All ten current v515 backend tests pass. The merged Kraken connection/startup/bridge/composition regressions also pass: 63 tests and three subtests. A mutation probe replacing one reviewed test key with a different synthetic candidate remains unbaselined. Five reviewed files pass the complete baseline-aware file hook; the sixth retains its separate unreviewed entropy candidate.

The full tracked-file scan must still reject every remaining unreviewed candidate. These nine dispositions do not certify the repository, prove production account identity, reconcile fills, install a collector, or authorize deployment. Independent review, all exact-release and image checks, and production backup/restore evidence remain necessary.

## Pre-commit failure evidence

The former uploaded artifact contained only an overall outcome and a request to read the full log. When the log transport fails, that artifact cannot identify an installation problem or a failed hook. The workflow now runs the same all-file command through a bounded, shell-free wrapper. It records fixed allowlisted hook IDs, fixed error categories, and the real exit status in JSON. It never publishes raw scanner output, source diffs, candidate values, or exception text. Unknown failures remain failures. Missing executables, timeouts, abnormal exits, and contradictory success reports fail closed.

Nine offline reporter tests pass, covering preserved failure codes, missing runners, timeouts, modified files, colorized output, and non-disclosure. The workflow executes these regressions before invoking pre-commit. Actual hosted pre-commit certification remains required; diagnostic coverage does not establish that all hooks pass. Bandit reports only two low-severity subprocess cautions for the fixed argument-vector invocation; no medium/high findings were introduced.
