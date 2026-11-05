# Protective mapping schema repair: rehearsal and approval boundary

Recovery run 41969472782 verified the deployed identity, runtime source,
authenticated shell and SQLite integrity, then refused collector installation
because the canonical ledger lacks protective-order mapping columns and has
pending Kraken closes. Its completed historical capture does not establish
fresh account ownership, complete reconciliation or current protective exits.

`scripts/nija_protective_mapping_rehearsal.py` prepares the schema portion of
the repair on a separate candidate from a closed private backup. It opens the
backup read-only, requires its exact SHA-256, refuses SQLite sidecars and
existing destinations, and publishes the candidate with mode 0600. Each
original table/cell and non-position schema object must remain unchanged.
An interrupted or rejected transaction publishes no candidate. The original
backup is never edited.

The only schema additions are nullable TEXT columns `stop_order_id` and
`take_profit_order_id` in `open_positions`. Existing columns and mappings are
preserved. Missing values stay NULL. Pending closes remain pending. An added
column is not an exchange protective order; the normal preflight continues
to reject missing/unverified exits and unreconciled closes.

## Isolated use

Run with Python's startup hooks disabled, using a previously obtained closed
backup in a private owner-only directory. Supply the independently verified
backup digest; do not calculate it from an arbitrary input and assume that
establishes provenance. The candidate path must be new and outside the running
service's state directory.

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -B -S scripts/nija_protective_mapping_rehearsal.py \
  --backup /absolute/private-review/closed-backup.db \
  --candidate /absolute/private-review/schema-candidate.db \
  --expected-backup-sha256 "$REVIEWED_BACKUP_SHA256"
```

There is no production apply mode. Render/Railway runtime environments and
source/destination paths under `/app` or `/data` are refused. This command is not a deployment or
migration approval. Keep candidate databases and backup material private;
do not commit or attach them to public GitHub issues, PRs or Actions artifacts.
The digest-only report explicitly leaves production application, backup
origin, off-host restore certification, broker reconciliation, protective
coverage and order authorization false.

## Required completion before any production write

1. Obtain a coherent current backup tied to the approved deployment/account;
   verify an encrypted off-host copy and an isolated restore independently.
2. Run the rehearsal on that restored backup. Review exact added columns,
   source/candidate digests and preservation evidence. The current tests use
   synthetic fixtures; they are not a production restore rehearsal.
3. Use fresh authenticated account-bound Kraken records, complete pagination,
   and exact order/fill links to reconcile pending closes. Review cost basis,
   quantities, fees, partial fills, ledger entries and remaining positions.
   Never mark a close reconciled solely because a historical receipt exists.
4. Read back actual protective orders and verify their account, pair, side,
   quantity and execution constraints before recording any ID. Price levels,
   locally generated client IDs and guessed broker IDs are insufficient.
5. Review a separate exact production transaction and rollback procedure with
   the qualified reviewer and owner. Keep a verified pre-change restore point.
   This tool cannot execute that transaction or write reconciliation results.
6. Resolve mandatory security failures and obtain the separately required
   schema/release approvals. Keep the Render hold and canonical order gates.
7. After approved application, reverify broker/ledger consistency, protective
   coverage and all 13 fresh production observations. This is still separate
   from exact-order approval and POSTTRADE_VERIFIED commissioning.

For this isolated rehearsal, rollback is discarding its candidate; the source
is unchanged. That is not a claimed rollback plan for a live ledger mutation.
