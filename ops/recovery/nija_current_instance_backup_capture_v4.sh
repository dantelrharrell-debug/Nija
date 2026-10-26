#!/usr/bin/env bash
# NIJA recovery v4. Operator-only, on EXISTING running Render instance.
# Read-only sources. Private /tmp archive output. Never deploy/trade from here.
set -Eeuo pipefail
umask 077
trap 'rc=$?; printf "SOURCE_CAPTURE=FAILED_CLOSED exit_code=%s\n" "$rc" >&2' ERR

readonly EXPECTED_SERVICE='srv-d98dsr5aeets73fpbaqg'
readonly EXPECTED_COMMIT="${NIJA_EXPECTED_DEPLOYED_COMMIT:-}"
readonly DATA_ROOT=/data
readonly LEDGER=/data/trade_ledger.db
readonly POSITIONS=/app/data/positions
readonly ENTRY_PRICES=/app/data/entry_prices
readonly -a FILES=(
  nija_state_store_persistence_audit_v441.py
  nija_trade_ledger_snapshot_v436.py
  nija_account_state_offhost_evidence_v449.py
  nija_legacy_global_state_evidence_v462.py
)
cd /app

if [[ ! "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ || "${RENDER_SERVICE_ID:-}" != "$EXPECTED_SERVICE" || "${RENDER_GIT_COMMIT:-}" != "$EXPECTED_COMMIT" ]]; then
  echo 'STOP: provide independently confirmed NIJA_EXPECTED_DEPLOYED_COMMIT (40-char SHA) matching the actual Render service deployment' >&2
  exit 1
fi

test -s "$LEDGER" || { echo 'STOP: current SQLite ledger unavailable' >&2; exit 1; }
for dir in "$POSITIONS" "$ENTRY_PRICES"; do
  [[ -d "$dir" ]] || { echo 'STOP: current account-state directory unavailable' >&2; exit 1; }
done
for name in "${FILES[@]}"; do
  [[ -s "scripts/$name" && ! -L "scripts/$name" ]] || {
    echo 'STOP: missing or linked source verifier' >&2; exit 1;
  }
done

# Verified Git object IDs of the four files in the deployed release commit.
# This is an exact source-code pin, NOT a broker-identity attestation.
python -S - <<'PY'
import hashlib
from pathlib import Path
pins = {
  'nija_state_store_persistence_audit_v441.py': '54b8109658dd7ca9031edad7c0092f3402b92613',
  'nija_trade_ledger_snapshot_v436.py': '2899aa5e1e23a08ceba8af2bb9b0df7e2011aeca',
  'nija_account_state_offhost_evidence_v449.py': 'bab7e59613b3777a803213496021f5eab09731c0',
  'nija_legacy_global_state_evidence_v462.py': '2ae98af7e7edfc4be4be413a46ae2ff877c44726',
}
for name, expected in pins.items():
  raw = (Path('/app/scripts') / name).read_bytes()
  actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
  if actual != expected:
    raise SystemExit('STOP: deployed-source Git blob mismatch: ' + name)
print('SOURCE_VERIFIER_GIT_BLOB_PINS=PASS')
root = Path('/data').resolve(strict=True)
for label, path in (
  ('ledger', Path('/data/trade_ledger.db')),
  ('positions', Path('/app/data/positions')),
  ('entry_prices', Path('/app/data/entry_prices')),
):
  resolved = path.resolve(strict=True)
  if resolved == root or root not in resolved.parents:
    raise SystemExit('STOP: ' + label + ' is outside mounted /data')
  if (label == 'ledger' and not resolved.is_file()) or (label != 'ledger' and not resolved.is_dir()):
    raise SystemExit('STOP: unsafe source file type for ' + label)
print('SOURCE_PERSISTENT_PATHS=PASS')
PY

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
out="$(mktemp -d /tmp/nija-current-recovery-v4-XXXXXXXX)"
[[ -d "$out" && ! -L "$out" && -O "$out" ]] || { echo 'STOP: private output directory ownership/type invalid' >&2; exit 1; }
mode="$(stat -c %a "$out")"
(( (8#$mode & 0077) == 0 && (8#$mode & 0700) == 0700 )) || {
  echo 'STOP: output must deny all group/other access and allow owner access' >&2; exit 1;
}
mkdir -m 700 "$out/verifiers"
for name in "${FILES[@]}"; do
  install -m 600 "scripts/$name" "$out/verifiers/$name"
done

python -S scripts/nija_state_store_persistence_audit_v441.py \
  --persistent-root "$DATA_ROOT" --ledger "$LEDGER" \
  --positions-dir "$POSITIONS" --entry-prices-dir "$ENTRY_PRICES" \
  > "$out/source_persistence_audit.json"
python -S scripts/nija_trade_ledger_snapshot_v436.py backup \
  --source "$LEDGER" --output-dir "$out" \
  > "$out/ledger_snapshot_receipt.json"
python -S scripts/nija_account_state_offhost_evidence_v449.py snapshot \
  --persistent-root "$DATA_ROOT" --positions-dir "$POSITIONS" \
  --entry-prices-dir "$ENTRY_PRICES" --output-dir "$out" \
  > "$out/account_state_receipt.json"
python -S scripts/nija_legacy_global_state_evidence_v462.py snapshot \
  --persistent-root "$DATA_ROOT" --output-dir "$out" \
  > "$out/legacy_state_receipt.json"

python -S - "$out" "$started" "$EXPECTED_SERVICE" "$EXPECTED_COMMIT" <<'PY'
import datetime
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
for name in ('source_persistence_audit.json','ledger_snapshot_receipt.json',
             'account_state_receipt.json','legacy_state_receipt.json'):
  value = json.loads((root / name).read_text('utf-8'))
  if not isinstance(value, dict) or value.get('status') == 'FAILED_CLOSED':
    raise SystemExit('STOP: incomplete/failed source receipt')
  if name == 'source_persistence_audit.json' and value.get('storage_paths_aligned') is not True:
    raise SystemExit('STOP: mounted source audit did not pass')
context = {
  'source_capture_started_utc': sys.argv[2],
  'source_capture_completed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'source_service_id': sys.argv[3], 'source_deployed_sha': sys.argv[4],
  'same_instance_file_sources_observed': True,
  'sqlite_wal_consistent_snapshot_observed': True,
  'account_state_json_captured': True,
  'cross_store_atomicity_verified': False,
  'broker_order_history_reconciled': False,
  'off_host_custody_verified': False,
  'encryption_key_recoverability_verified': False,
  'trading_authorized': False, 'deployment_authorized': False,
  'executed_on_existing_instance': True,
}
(root / 'CAPTURE_CONTEXT.json').write_text(json.dumps(context,sort_keys=True,indent=2)+'\n',encoding='utf-8')
PY

(
  cd "$out"
  shopt -s nullglob
  ledgers=(nija-trading-ledger-*.tar.gz)
  accounts=(nija-account-state-*.zip)
  legacy=(nija-legacy-state-*.zip)
  (( ${#ledgers[@]} == 1 && ${#accounts[@]} == 1 && ${#legacy[@]} == 1 )) || {
    echo 'STOP: missing or ambiguous archive' >&2; exit 1;
  }
  for a in "${ledgers[@]}" "${accounts[@]}" "${legacy[@]}"; do
    [[ -f "$a" && ! -L "$a" ]] || { echo 'STOP: unsafe archive type' >&2; exit 1; }
  done
  sha256sum -- "${ledgers[@]}" "${accounts[@]}" "${legacy[@]}" > SHA256SUMS
  sha256sum -- CAPTURE_CONTEXT.json source_persistence_audit.json \
    ledger_snapshot_receipt.json account_state_receipt.json \
    legacy_state_receipt.json > EVIDENCE_SHA256SUMS
  sha256sum -- verifiers/*.py > VERIFIERS_SHA256SUMS
  sha256sum --check --status SHA256SUMS
  sha256sum --check --status EVIDENCE_SHA256SUMS
  sha256sum --check --status VERIFIERS_SHA256SUMS
  # Never write this source-side seal into the transferred capture directory.
  seal="$(sha256sum SHA256SUMS EVIDENCE_SHA256SUMS VERIFIERS_SHA256SUMS | sha256sum | cut -d' ' -f1)"
  printf 'SOURCE_CAPTURE_SEAL_SHA256=%s\n' "$seal"
)
printf 'SOURCE_CAPTURE=COMPLETE\nCAPTURE_DIR=%s\n' "$out"
printf 'NEXT=TRANSFER_ENTIRE_PRIVATE_DIRECTORY_BY_ENCRYPTED_SSH_AND_PRESERVE_SOURCE_SEAL_OUT_OF_BAND\n'
printf 'OFF_HOST_RESTORE_REQUIRED=true\nTRADING_AUTHORIZED=false\n'