# Kraken connector artifact preflight

After independent review and controlled provisioning of the existing protected
Kraken connector files, an authorized operator can run this read-only diagnostic
from the service checkout in the exact intended Render service/release:

```sh
python -B -m bot.kraken_connector_preflight
```

Run neither the trading bootstrap nor the protected Python to perform this
check. The command does not launch the application, contact Kraken or Redis,
write files, register or install a collector, or place/cancel orders. It reads
the two fixed protected paths using the production loader's file checks,
verifies the three signed receipts with its existing verifier, and compares the
protected Python bytes to the signed independent-review digest. It uses the
actual Render service and commit environment metadata; do not override these
values to obtain a passing production result.

Only a fixed JSON status is printed. Exit code zero says the signatures and
source digest match the provisioned manifest and runtime scope. It does **not**
prove the correctness of the approved source, authenticate the trust anchors or
the running image independently, verify the underlying evidence, prove account
connectivity, install a collector, or authorize orders. The existing deployment
and pretrade gates still apply. Missing or unsafe files, invalid manifests,
invalid/expired receipts, mismatched runtime scope, and changed bytes fail with
a nonzero exit. Do not attach manifest contents, source artifacts, private keys,
or receipts to tickets or messages.
