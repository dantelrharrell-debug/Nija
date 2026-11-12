# Canonical Kraken collector factory — review candidate

This change implements a concrete factory for the existing startup binding API.
It does **not** install a production collector, certify any live observation,
change the protected bootstrap, or enable orders. The protected final Python
composition root must still supply actual reviewed source objects and authentic
signed receipts. No environment factory loader or approval fallback is added.

## Research and architectural findings

- [Python 3.11 exec semantics](https://docs.python.org/3.11/library/os.html#os.execvpe):
  exec replaces the process image. In-memory registration in the outer ledger
  bootstrap cannot survive its Bash/Python handoff.
- [Render Docker secrets](https://render.com/docs/docker-secrets): runtime secret
  files can remain outside the repository/image. Production credentials must
  not enter GitHub or build arguments.
- [Kraken nonce guidance](https://support.kraken.com/au/articles/360001148063-why-am-i-getting-invalid-nonce-errors-):
  simultaneous callers sharing a key can produce out-of-order nonce errors.
  This factory reuses the canonical broker; it creates no second client or nonce owner.
- [Current GetApiKeyInfo](https://docs.kraken.com/api-reference/account-data/get-api-key-info)
  documents apiKey, iban, permissions and validUntil. Missing identity/expiry
  fields cannot be replaced with configured values or assumed non-expiration.
- [Current OpenOrders](https://docs.kraken.com/api-reference/account-data/get-open-orders)
  documents cursor pagination. Existing completeness checks remain mandatory.
- [Current AddOrder](https://docs.kraken.com/api-reference/trading/add-order)
  defines cl_ord_id uniqueness for open orders. This does not establish complete
  historical duplicate-prevention coverage; retain the independent durable inventory.

## Implemented connection path

The protected root explicitly calls
`register_canonical_kraken_collector_startup(trust=..., resolve_sources=..., review_sources=...)`
in the same interpreter that will run canonical main. The function registers
both the factory and the existing authenticated receipt verifier. It does not
resolve sources or install at registration time.

When bot_main's existing step 2.5 startup hook invokes that factory:

1. Select exactly one connected native KrakenBroker from the supplied canonical
   manager, in platform:kraken scope, with the existing private-call method.
2. Call the independently reviewed resolver with those exact manager, strategy
   and broker objects. It must return ReviewedCanonicalKrakenSources for those
   same objects, not a new broker, strategy or manager.
3. Require the separate source-object review callback to return literal True.
   This callback must authenticate real external review; it must not approve
   merely because the structural checks pass.
4. Validate all six independent sources and their reviewed owners. Compose the
   existing seven broker/protection/writer/nonce providers using the immutable
   account/key pins and thirteen provider IDs from StartupReceiptTrust.
5. Recheck source review and the canonical broker after construction; return an
   immutable ReviewedStartupBinding carrying the real signed receipts.
6. The existing startup hook authenticates the three receipts and atomically
   observes/validates all thirteen providers before replacing the collector.
   Any failure retains the existing collector and leaves admission unchanged.

The built-in provider constructors perform no broker reads. External resolver
and review implementations are trusted code requiring separate audit, including
object ownership, no side effects, source freshness and review legitimacy.
The wrapper cannot establish these facts simply by inspecting a callable.

## Required live inputs — not created by this change

| Input | Existing required owner/interface |
|---|---|
| Canonical manager, strategy, broker | Existing production objects passed by bot_main; no new clients |
| independently approved account/key, release/image pins and signer public keys | StartupReceiptTrust from protected review records |
| open-intent and position readers | Complete current independently reconciled ledger snapshots |
| position_ledger_reconciliation | Independent ledger provider with verified scoped schema/history |
| duplicate_order_fence | Durable complete submission inventory, independently reviewed coverage |
| operator_authorization | Real signed approval and current signed status, approved trust roots |
| kill_switch_clear | Existing risk/Redis owners and authenticated durable clearance binding |
| risk_limits | Complete atomic account/key-scoped risk snapshot source with authentic revisions |
| position_sync | Authenticated current holdings and complete ledger/adoption readback |
| three receipt envelopes | Genuine independent_review, backup_restore, broker_ledger_exits certifications |

Production's complete risk snapshot source and durable duplicate-inventory
binding have not been established. This factory does not synthesize either.
A green global risk flag, healthy heartbeat or empty local SQLite table cannot
replace these required facts. It does not change the issuer/key-custody process
or create a protected startup invocation. Those production installation steps
remain unfinished until the reviewed inputs exist and release checks pass.

## Validation limits

The new offline tests use ephemeral synthetic signing keys and synthetic source
owners, never production receipts. One path exercises the real seven-provider
construction with no broker I/O. A separate path uses synthetic provider bodies
with the real receipt verifier and atomic installer; it proves the software
handoff only and always reports authorizes_orders=false. Missing sources,
foreign canonical objects, changed owners/review, invalid receipts and resolver
payload leaks are denied. These tests are not production certification.

Mandatory release/security checks and independent review remain required.
Deploy only the approved exact release after explicit owner approval. Keep new
orders disabled until genuine live commissioning succeeds; obtain separate
pair, maximum amount and order-type approval before any first live order.
