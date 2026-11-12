# Native four-source construction in canonical startup

The existing canonical factory could reuse native kill-switch and position-sync
readers, but required four already-constructed external callbacks for the other
owners. The earlier four-source review added documentation/tests, not this
construction path. This change calls four existing native implementations:

| Field | Actual implementation | Required from the reviewed root |
| --- | --- | --- |
| position_ledger_reconciliation | make_kraken_ledger_evidence_provider | ReviewedLedgerBinding, authentic binding reviewer and complete certified independent ledger |
| duplicate_order_fence | RedisEvidenceReader.collect | Existing Redis client, ReviewedBinding, actual scope observer and authenticated complete durable inventory coverage |
| operator_authorization | make_general_operator_authorization_provider | GeneralApprovalBinding, provisioned operator/status trust roots and genuine current signed-record reader |
| risk_limits | make_kraken_risk_limits_provider | Authenticated atomic account-risk publisher, exact capital/exposure/policy source IDs and optional existing veto owners |

The protected resolver may supply `native_four_sources` and
`review_native_four_sources` on ReviewedCanonicalKrakenSources. The former is
ReviewedNativeFourSources with explicit manager/strategy/broker references and
service/release/image pins. The latter must authenticate actual source ownership,
Redis deployment/coverage/source-artifact pins and trust roots, returning literal
True only after establishing that review. Matching field names or copying trust
pins is not proof. Review includes the protected artifact's transitive code in
the exact image. Supplied callbacks/objects are reviewed trusted code, not a
sandbox: their implementations must also be audited for side effects.

Construction checks exact canonical objects, release/account/key/IIBAN/provider
pins and the ledger monitoring boundary. It creates native readers without
sampling them, then rechecks validity and review. The same binding checks,
current canonical broker membership and authenticated review run before and
after each native observation; revoked review discards returned evidence.
The full six-role owner map
remains mandatory. Without native pair bindings, independent_remaining supplies
only the existing kill_switch_clear and position_sync callbacks. With the native
pair, supply an empty map and the factory constructs all six readers. Overlapping
or mixed sources are rejected. Both original external-callback modes remain.

Actual reviewed independent_open_intents and independent_positions readers are
still mandatory. No backing data is discovered, initialized or certified here.
RedisEvidenceReader checks its three fencing observations together; only its
duplicate-fence row is selected, leaving existing canonical writer/nonce
providers unchanged. Each observation reads anew; no cached proof is introduced.

This is not the production publisher/cutover implementation. It creates no
ledger backfill, production migration, inventory writes, coverage signatures,
operator approvals, account-risk data or certification receipts. Empty databases,
partial SCANs, TTL reservations, global reports and truthy flags cannot become
authenticated evidence. All native completeness, provenance, freshness,
revocation, fencing, nonce, position and protective-exit checks remain intact.
Failures prevent atomic installation and preserve a previous collector.

Offline tests use synthetic owners/signers only: real native construction,
canonical/protected same-interpreter reachability, pin/review denial before
reads, and real atomic denial without native data. The existing Docker shell
probe requires this module to be packaged; recipes and production pins remain
unchanged.

This candidate installs no protected files, changes no production configuration,
deploys nothing and authorizes no orders. Actual source objects/data, reviewed
trust provisioning, genuine certifications, passing mandatory release/security
checks, credential-rotation verification and owner deployment approval remain
required. First-order and autonomous-trading approval remain separate.
