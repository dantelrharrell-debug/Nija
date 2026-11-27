# Signed protected root in canonical startup — review candidate

The deployed startup calls the atomic collector installer but never registers
its factory/verifier in that interpreter. This change adds an actual caller in
`bot_main` after canonical strategy publication and before the existing installer
and trading-engine startup. It preserves the protected ledger bootstrap, shell
handoffs, writer acquisition, canonical broker and nonce ownership. It creates
no new service, broker client, nonce owner, execution adapter or order authority.

## Protected artifact contract

The independently reviewed deployment owner must provision both fixed files:

- `/etc/secrets/.render-kraken-startup-binding.json`
- `/etc/secrets/.render-kraken-startup-root.py`

The existing Render command remains `python -S /etc/secrets/.render-ledger-bootstrap.py`.
Do not put the registration call in that outer process: its exec handoff discards
in-memory state. The new hook runs in the final canonical process instead.
No environment variable can select a source path, module, signer or provider.

The JSON object has exactly `contract`, `trust`, and `receipts`. Its contract is
`nija.kraken-protected-startup-binding.v1`. `trust` contains the existing
StartupReceiptTrust fields: service/release/image pins, independently approved
account and credential fingerprints, thirteen distinct reviewed provider IDs,
three role-pinned public keys encoded as lowercase hex, and the bounded maximum
receipt age. `receipts` contains the existing three **serialized signed JSON
envelopes**, one per required certification role. Private signing keys and
credentials must never enter this manifest or the repository.

**The manifest is a provisioned trust anchor, not evidence of its own approval.**
Its keys and pins must come from independent review and controlled owner
provisioning. Generating new keys and signing unverified claims does not satisfy
this requirement. File ownership/mode and valid signatures do not independently
establish that the issuer actually performed the required review or tests.

The existing receipt verifier authenticates all three signatures, distinct
evidence IDs, role, exact runtime service/release, account/key/image/registry
scope, approved time and expiry before any protected Python runs. The
`independent_review` receipt's `artifact_sha256` must identify the exact complete
protected Python source, including its source-owner review implementation.
The backup/restore and broker-ledger/exits receipts still identify genuine
verified artifacts. All three checks run again after source loading, and again
against the constructed binding before the existing atomic installer samples
the thirteen observations.

Runtime service/release metadata are checked against the existing Render
variables. Image-hash agreement here compares signed pins; it is not an
independent observation of the running image. Exact-image verification remains
mandatory external release work.

The protected source must define:

- `resolve_sources(*, manager, strategy, broker, trust, receipts)` returning the existing
  `ReviewedCanonicalKrakenSources` for those exact runtime objects and those
  same frozen signed receipts;
- `review_sources(sources, *, trust)` authenticating the independent review of the actual
  live source objects and owners, returning literal True only when established.

`trust` is the immutable, validated StartupReceiptTrust from the protected
manifest, not pins learned from a first exchange response. Its provider IDs and
account/key pins are available to both callbacks without rereading configuration.

The resolver may retain six external callbacks, or supply four external callbacks
with explicit `kill_switch_binding` and `review_kill_switch_binding` fields in
ReviewedCanonicalKrakenSources. The canonical factory then uses the existing
reviewed native kill-switch and position-sync constructors. It still requires
the full six-role owner map and validates all thirteen observations before
installation. No clearance, holding, adoption state or approval is inferred
from selecting this mode; see the canonical-factory contract for exact inputs.

The complete implementation must be reviewed, including imported modules and
transitive source dependencies in the exact release image. A blanket True
reviewer, synthetic providers, guessed identity pins, global risk booleans, or
an empty/partial Redis inventory is unacceptable. This document supplies no
production resolver, fabricated observations, signers, keys or passing receipts.

## Boundaries and failure behavior

Approved Python runs with production-process privileges. This is **not a
sandbox** and cannot make malicious approved code safe. The protected source
must have passive import behavior, no order/network/ledger side effects, and
use only the existing canonical owners when its resolver later runs. Source
hash authentication covers the entry file; independent review of the exact
image and transitive imports remains mandatory.

The reader bounds file sizes, accepts only regular non-group/world-writable
files owned by root or the current process owner, and permits Render-style
versioned secret symlinks only within the fixed protected mount. The loader
compiles the same frozen bytes that were checked; it cannot reopen a changed
source or substitute a bytecode cache. Registration during approved-source
import is rejected to catch accidental top-level registration. That guard is
not protection against a malicious approved module mutating arbitrary globals.

A pre-existing process registration is preserved. Missing/invalid protected
artifacts, wrong signatures/scope, changed source bytes, expiry, bad interface,
or import exceptions produce fixed non-sensitive statuses and no new
registration. No protected contents, exception payloads or credential values
are logged. Missing artifacts continue to the unchanged installer/monitoring
path; no safety gate, existing position or protective exit is cleared.

The success status `protected_startup_factory_registered` means only that the
factory and authenticated verifier were registered. It is not collector
installation, a successful observation, completed certification, or order
authorization. Actual installation still requires the existing canonical
object checks, six independently owned sources, three genuine receipts and
all thirteen valid fresh observations before replacing the collector.

## Validation and unresolved production work

Offline tests use ephemeral synthetic signers and owners only. They cover
receipt/signature/source/runtime failures before code execution, original-byte
loading, secret-file constraints, import registration denial, preservation of
existing state, an actual OS exec followed by fresh final-interpreter
registration, real thirteen-provider construction without broker reads, and a
separate synthetic-observation path through the real atomic installer with
orders unauthorized. CI explicitly runs these tests on Python 3.11.

The isolated Docker test uses the existing production recipe and network-off
shell fixture to inspect the packaged modules and caller order after real shell
patchers run. The Dockerfile and production approval/source pins are not
changed by this startup handoff. An initial optional Dockerfile compilation
addition was removed. The recovered base Dockerfile already differs from the
two previously recognized recipes: public commit
[6e34c616](https://github.com/dantelrharrell-debug/Nija/commit/6e34c616861aa3f81fc91e54bacf6f7ee62ee18f)
adds only `apt-get upgrade -y` to the existing package-install line. A byte-for-
byte comparison with the prior recognized recipe at
[25ae1de6](https://github.com/dantelrharrell-debug/Nija/commit/25ae1de671e037d458eece243dac393e7f8d7e0e)
verified that exact one-line difference. This proposal adds that exact public
recipe checksum to the derivation verifier, preserving the two existing
checksums, every patcher pin and the default denial of all other bytes. Existing
tests reproduce the real script rewrites; a new negative test rejects altered
upgrade flags. This recognition is subject to human review and does not certify
package/image security, update production approval/source pins or approve a
deployment. The checksum is public code metadata, not a credential.

The production risk snapshot source, complete durable duplicate inventory,
independent ledger provenance/readers, actual source review, current account
reconciliation/protection, genuine signed certifications and approved trust
anchors remain required. The historical backup restore test is not a current
production certification. Existing failing release/security checks and exposed
credential rotation verification remain unresolved by this change.

This PR installs no protected files, changes no Render settings, deploys
nothing, and enables no orders. Require independent human review and successful
mandatory checks on the exact release/image before requesting approval to
provision/deploy this protected connection. First live orders still require
separate pair, maximum amount and order-type approval; autonomous trading
requires another explicit approval.
