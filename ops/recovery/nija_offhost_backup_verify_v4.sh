#!/usr/bin/env bash
# NIJA recovery v4. Operator runs on independent private machine, NEVER on Render.
# Usage: bash nija_offhost_backup_verify_v4.sh PRIVATE_CAPTURE_DIR SOURCE_CAPTURE_SEAL_SHA256
# Source seal must come from independently retained source terminal output,
# NOT from a file bundled with the transferred capture directory.
set -Eeuo pipefail
umask 077
trap 'rc=$?; printf "OFF_HOST_VERIFICATION=FAILED_CLOSED exit_code=%s\n" "$rc" >&2' ERR
if (( $# != 2 )) || [[ ! "$2" =~ ^[a-f0-9]{64}$ ]]; then
  echo 'Usage: nija_offhost_backup_verify_v4.sh PRIVATE_CAPTURE_DIR SOURCE_CAPTURE_SEAL_SHA256' >&2
  exit 2
fi
capture="$(cd -- "$1" && pwd -P)"
expected_seal="$2"

python -S - "$capture" "$expected_seal" <<'PY'
import hashlib
import json
import pathlib
import re
import stat
import sys
root = pathlib.Path(sys.argv[1]); expected_seal = sys.argv[2]
verifier_dir = root / 'verifiers'
pins = {
  'nija_state_store_persistence_audit_v441.py': '54b8109658dd7ca9031edad7c0092f3402b92613',
  'nija_trade_ledger_snapshot_v436.py': '2899aa5e1e23a08ceba8af2bb9b0df7e2011aeca',
  'nija_account_state_offhost_evidence_v449.py': 'bab7e59613b3777a803213496021f5eab09731c0',
  'nija_legacy_global_state_evidence_v462.py': '2ae98af7e7edfc4be4be413a46ae2ff877c44726',
}
patterns = (
  re.compile(r'nija-trading-ledger-[0-9]{8}T[0-9]{6}Z-[a-f0-9]+\.tar\.gz'),
  re.compile(r'nija-account-state-[0-9]{8}T[0-9]{6}Z-[a-f0-9]+\.zip'),
  re.compile(r'nija-legacy-state-[0-9]{8}T[0-9]{6}Z-[a-f0-9]+\.zip'),
)
for d in (root, verifier_dir):
  if d.is_symlink() or not d.is_dir() or stat.S_IMODE(d.stat().st_mode) & 0o077:
    raise SystemExit('STOP: missing/unprivate evidence directory')
archives = []
for pattern in patterns:
  matches = [p.name for p in root.iterdir() if pattern.fullmatch(p.name)]
  if len(matches) != 1:
    raise SystemExit('STOP: missing or ambiguous recovery archive')
  archives.extend(matches)
evidence = ['CAPTURE_CONTEXT.json','source_persistence_audit.json',
            'ledger_snapshot_receipt.json','account_state_receipt.json','legacy_state_receipt.json']
manifest_names = ['SHA256SUMS','EVIDENCE_SHA256SUMS','VERIFIERS_SHA256SUMS']
allowed_root = set(archives + evidence + manifest_names + ['verifiers'])
if {p.name for p in root.iterdir()} != allowed_root or {p.name for p in verifier_dir.iterdir()} != set(pins):
  raise SystemExit('STOP: unexpected or missing recovery bundle member')

def safe(path, maxsize=1024*1024*1024):
  if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > maxsize:
    raise SystemExit('STOP: unsafe or oversize recovery file')
  return path.read_bytes()

def manifest(name, names):
  lines = safe(root/name,8192).decode('ascii').splitlines()
  matches = {}
  for line in lines:
    m = re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.\-/]+)', line)
    if not m or m.group(2) in matches or m.group(2) not in names:
      raise SystemExit('STOP: corrupted/duplicate manifest')
    matches[m.group(2)] = m.group(1)
  if set(matches) != set(names):
    raise SystemExit('STOP: incomplete manifest')
  return matches

manifests = [manifest('SHA256SUMS',archives),
             manifest('EVIDENCE_SHA256SUMS',evidence),
             manifest('VERIFIERS_SHA256SUMS',['verifiers/'+x for x in pins])]
seal_contents = ''.join(
  hashlib.sha256(safe(root/name,8192)).hexdigest()+'  '+name+'\n'
  for name in manifest_names
).encode('ascii')
if hashlib.sha256(seal_contents).hexdigest() != expected_seal:
  raise SystemExit('STOP: independent source capture seal mismatch')
for md in manifests:
  for name, sha in md.items():
    if hashlib.sha256(safe(root/name)).hexdigest() != sha:
      raise SystemExit('STOP: transferred file checksum mismatch')
for name, sha in pins.items():
  raw = safe(verifier_dir/name,1024*1024)
  blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
  if blob != sha:
    raise SystemExit('STOP: unreviewed verifier source code')
context = json.loads(safe(root/'CAPTURE_CONTEXT.json',16384))
paths = json.loads(safe(root/'source_persistence_audit.json',32768))
if (context.get('source_service_id') != 'srv-d98dsr5aeets73fpbaqg'
    or context.get('source_deployed_sha') != '0ae35d1b2b84dc788bfd6ae10a8b459ae806a752'
    or context.get('deployment_authorized') is not False
    or context.get('trading_authorized') is not False
    or context.get('executed_on_existing_instance') is not True
    or paths.get('storage_paths_aligned') is not True):
  raise SystemExit('STOP: source identity, audit or authorization invariant missing')
for filename in evidence[2:]:
  receipt = json.loads(safe(root/filename,32768))
  if not isinstance(receipt, dict) or receipt.get('status') == 'FAILED_CLOSED':
    raise SystemExit('STOP: invalid archive capture receipt')
print('OFF_HOST_SOURCE_SEAL=PASS')
print('OFF_HOST_ARCHIVE_AND_RECEIPT_HASHES=PASS')
print('OFF_HOST_PINNED_VERIFIERS=PASS')
PY

shopt -s nullglob
ledgers=("$capture"/nija-trading-ledger-*.tar.gz)
accounts=("$capture"/nija-account-state-*.zip)
legacy=("$capture"/nija-legacy-state-*.zip)
source_digest() {
  local name; name="${1##*/}"
  awk -v wanted="$name" '$2 == wanted {print $1}' "$capture/SHA256SUMS"
}
python -S "$capture/verifiers/nija_trade_ledger_snapshot_v436.py" restore-test \
  --archive "${ledgers[0]}" --expected-sha256 "$(source_digest "${ledgers[0]}")"
python -S "$capture/verifiers/nija_account_state_offhost_evidence_v449.py" verify \
  --archive "${accounts[0]}" --expected-sha256 "$(source_digest "${accounts[0]}")"
python -S "$capture/verifiers/nija_legacy_global_state_evidence_v462.py" verify \
  --archive "${legacy[0]}" --expected-sha256 "$(source_digest "${legacy[0]}")"
printf 'OFF_HOST_RESTORE_AND_ARCHIVE_VERIFICATION=PASS\n'
printf 'CROSS_STORE_ATOMICITY=UNVERIFIED\nHISTORICAL_BROKER_RECONCILIATION=UNVERIFIED\n'
printf 'ENCRYPTED_CUSTODY_KEY_RECOVERY=UNVERIFIED\nPRODUCTION_DEPLOY_AUTHORIZED=false\nTRADING_AUTHORIZED=false\n'