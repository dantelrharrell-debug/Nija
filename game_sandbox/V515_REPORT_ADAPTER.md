# Approved v515 report adapter

The approved game has newer scoring than `ionos_published_report.mjs`. For the
standard Beginner all-hold run with stop enabled every third round, v515 scores
93 while the old report scores 50. Do not reuse the old report for v515 purchases.

`v515.py` and `v515_runner.mjs` connect the approved, checksum-pinned v515 report,
engine and scoring modules to the existing `Sandbox` entitlement boundary. They
do not replace the legacy adapter, change gameplay or activate checkout. The
existing raw-body webhook, fresh provider verification, durable per-run checkout,
owner cookie, refund/dispute and replay protections remain in `service.py`.

The v515 manifest has a new identity; a legacy stored run or purchase cannot be
silently treated as a purchase for v515. The original approved source is unchanged.

After provisioning and certifying the existing isolated sandbox, select the
adapter with `NIJA_IQ_SANDBOX_GAME=v515` and pin its manifest digest in
`NIJA_IQ_SANDBOX_MANIFEST_SHA256`. `create_app` passes this same trusted manifest
to the existing frontend asset integrity check. An old frontend manifest fails
startup. The existing default and `published72` paths are preserved.

The eight tests in `test_v515.py` use temporary SQLite storage and a fake provider.
They verify the canonical score, incomplete/tampered input denial, source integrity,
repeated checkout and webhook deduplication, ownership, refunds/disputes and legacy
manifest rejection. They do not establish real Stripe sandbox transactions,
cryptographic webhook delivery, public browser integration or secure cross-device
recovery. No live credentials are accepted by the existing sandbox configuration.

Remaining release work includes frontend integration, real sandbox checkout and
webhook tests, persistent storage certification, secure access recovery, device QA
and the repository's outstanding preflight/security findings. No production setting,
live payment, customer record, trading authorization or Founding 100 price changes.
