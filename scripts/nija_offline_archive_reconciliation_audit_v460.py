#!/usr/bin/env python3
"""Read-only NIJA *historical* recovery-archive and operator-CSV consistency audit.

This tool does not connect to Kraken or Render, alter production, authenticate an
account, establish current protective exits, or grant trading authorization.
It only checks an independently supplied local archive and CSV crosswalk.

Usage:
 python -S scripts/nija_offline_archive_reconciliation_audit_v460.py \
   --archive HISTORICAL_RECOVERY.tar.gz \
   --expected-archive-sha256 INDEPENDENTLY_RECORDED_SHA256 \
   --crosswalk CROSSWALK.csv --report /private/location/report.json

Input files are not changed. The report contains no raw holdings, user account
identities, or exchange order IDs. Keep source archives/CSVs in restricted storage.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import stat
from pathlib import Path, PurePosixPath
import sqlite3
import tarfile
import tempfile

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_CSV_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
SHA256_HEX = frozenset("0123456789abcdef")
REQUIRED_TABLES = (
    'trade_ledger','open_positions','completed_trades',
    'strategy_order_intents','pending_kraken_closes',
)
REQUIRED_CSV = (
    'case','nija_order_id','nija_symbol','nija_side',
    'exact_order_id_match','pdf_trade_id_match',
    'pdf_both_ledger_ids_match','broker_authenticated_account_scope',
    'opening_cost_basis_verified','realized_pnl_certified',
)


def hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _pinned_read_file(path: Path, max_bytes: int) -> bytes:
    """Pin and bound regular-file input; reject symlinks and FIFOs without blocking.

    Use the opened inode, not a preliminary ``Path.is_file()`` check that can
    race with a rename. A mutation during the read invalidates the evidence.
    """
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("input_not_regular_file")
        if before.st_size < 0 or before.st_size > max_bytes:
            raise ValueError("input_exceeds_safety_limit")
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(max_bytes + 1)
        after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if signature(before) != signature(after) or len(data) != before.st_size:
            raise ValueError("input_changed_during_read")
        if len(data) > max_bytes:
            raise ValueError("input_exceeds_safety_limit")
        return data
    finally:
        os.close(fd)


def _expected_hash(value: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest).issubset(SHA256_HEX):
        raise ValueError("invalid_expected_archive_sha256")
    return digest


def _reject_nonfinite_json_constant(constant):
    raise ValueError("non_finite_json_number")


def _no_duplicate_json_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate_json_member_key")
        obj[key] = value
    return obj


def members(raw: bytes, max_total: int) -> dict[str, bytes]:
    """Bounded in-memory unpack; never write archive-controlled paths to disk."""
    # A tiny gzip can claim gigantic decompressed members (including gigantic
    # PAX headers). Bound decompression before tarfile parses any metadata.
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
        plain = compressed.read(max_total + 1)
    if len(plain) > max_total:
        raise ValueError('decompressed_archive_limit_exceeded')
    output: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as tar:
        for item in tar:
            p=PurePosixPath(item.name)
            if p.is_absolute() or not item.name or '..' in p.parts or '\\' in item.name:
                raise ValueError('unsafe archive member name')
            if item.isdir():
                continue
            if not item.isfile() or item.name in output:
                raise ValueError('special or duplicate archive member')
            if item.size < 0 or item.size > MAX_MEMBER_BYTES or total+item.size > max_total:
                raise ValueError('oversized archive')
            stream=tar.extractfile(item)
            if stream is None:
                raise ValueError('unreadable archive member')
            content=stream.read(item.size+1)
            if len(content) != item.size:
                raise ValueError('member size mismatch')
            output[item.name]=content
            total+=item.size
    return output


def database_inventory(db_bytes: bytes) -> tuple[dict[str,int|None],list[dict[str,str]]]:
    with tempfile.TemporaryDirectory(prefix='nija-archive-audit-') as folder:
        db_path=Path(folder)/'archived.db'
        with db_path.open('xb') as out:
            out.write(db_bytes)
        # Read-only mode preserves WAL semantics for isolated source copies.
        reader=sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            reader.row_factory=sqlite3.Row
            reader.execute('PRAGMA query_only=ON')
            rows=[tuple(row) for row in reader.execute('PRAGMA integrity_check')]
            if rows != [('ok',)]:
                raise ValueError('archived SQLite integrity check failed')
            names={row[0] for row in reader.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing=set(REQUIRED_TABLES)-names
            if missing:
                raise ValueError('required database tables missing')
            counts={name:int(reader.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
                    for name in REQUIRED_TABLES}
            status=reader.execute('SELECT order_id,symbol,side,broker,account_scope,state,verification_level FROM pending_kraken_closes').fetchall()
            pending=[{field:str(x[field]) if x[field] is not None else ''
                      for field in ('order_id','symbol','side','broker','account_scope','state','verification_level')}
                     for x in status]
            # Prove the archive's SQLite image can be restored in disposable storage.
            restored=Path(folder)/'isolated-restored.db'
            writer=sqlite3.connect(restored)
            try:
                reader.backup(writer,pages=256,sleep=0.1)
                writer.commit()
            finally:
                writer.close()
            with sqlite3.connect(restored.resolve().as_uri()+'?mode=ro',uri=True) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('isolated restore integrity failed')
                for name,n in counts.items():
                    if check.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]!=n:
                        raise ValueError('isolated restore count mismatch')
            return counts,pending
        finally:
            reader.close()


def audit(archive: Path, crosswalk: Path, expected_archive_sha256: str)->dict[str,object]:
    """Audit a historic archive pinned to a separately recorded source digest."""
    expected = _expected_hash(expected_archive_sha256)
    outer_raw=_pinned_read_file(archive,MAX_ARCHIVE_BYTES)
    if hash_bytes(outer_raw) != expected:
        raise ValueError("historical_archive_source_digest_mismatch")
    outer=members(outer_raw,MAX_ARCHIVE_BYTES)
    nested=[(name,content) for name,content in outer.items() if name.startswith('nija-trading-ledger-') and name.endswith('.tar.gz')]
    if len(nested)!=1:
        raise ValueError('expected one nested ledger archive')
    inner=members(nested[0][1],MAX_ARCHIVE_BYTES)
    if 'manifest.json' not in inner or 'trade_ledger.db' not in inner:
        raise ValueError('nested ledger and manifest required')
    manifest=json.loads(inner['manifest.json'], object_pairs_hook=_no_duplicate_json_keys, parse_constant=_reject_nonfinite_json_constant)
    if not isinstance(manifest,dict) or type(manifest.get('format_version')) is not int or manifest['format_version']!=1:
        raise ValueError('unexpected inner manifest format')
    tracked=manifest.get('members')
    if not isinstance(tracked,dict) or set(tracked)!=set(inner)-{'manifest.json'}:
        raise ValueError('inner manifest file inventory mismatch')
    for name,meta in tracked.items():
        if not isinstance(meta,dict) or meta.get('bytes')!=len(inner[name]) or meta.get('sha256')!=hash_bytes(inner[name]):
            raise ValueError('nested file digest/size mismatch')
    counts,pending=database_inventory(inner['trade_ledger.db'])
    for table,value in counts.items():
        if manifest.get('sqlite_tables',{}).get(table)!=value:
            raise ValueError('manifest database counts mismatch')
    if len(pending)!=counts['pending_kraken_closes']:
        raise ValueError('pending count mismatch')
    if any(not x['order_id'].strip() for x in pending) or len({x['order_id'] for x in pending})!=len(pending):
        raise ValueError('archived pending order ids missing or duplicate')
    if any(x['state']!='pending' or x['broker']!='kraken' or x['account_scope']!='platform:kraken' for x in pending):
        raise ValueError('unexpected archival pending scope/state')
    positions=[name for name in outer if name.startswith('positions/') and name.endswith('.json')]
    entry_prices=[name for name in outer if name.startswith('entry_prices/') and name.endswith('.json')]
    for name in positions+entry_prices:
        if not isinstance(json.loads(outer[name], object_pairs_hook=_no_duplicate_json_keys, parse_constant=_reject_nonfinite_json_constant),dict):
            raise ValueError('account JSON not object')
    csv_raw=_pinned_read_file(crosswalk,MAX_CSV_BYTES)
    text=csv_raw.decode('utf-8-sig')
    rdr=csv.DictReader(io.StringIO(text))
    if rdr.fieldnames is None or len(rdr.fieldnames)!=len(set(rdr.fieldnames)) or not set(REQUIRED_CSV).issubset(rdr.fieldnames):
        raise ValueError('crosswalk header invalid')
    records=list(rdr)
    if any(None in row for row in records):
        raise ValueError('malformed crosswalk CSV')
    evidence_ids=[str(row['nija_order_id']).strip() for row in records]
    if any(not x for x in evidence_ids) or len(set(evidence_ids))!=len(evidence_ids):
        raise ValueError('crosswalk order ids missing or duplicate')
    by_id={x['order_id']:x for x in pending}
    record_ids=set(evidence_ids)
    if record_ids != set(by_id):
        raise ValueError('crosswalk order IDs differ from archived pending orders')
    mismatches=[row['case'] for row in records if (
        row['nija_symbol']!=by_id[row['nija_order_id']]['symbol'] or
        row['nija_side'].lower()!=by_id[row['nija_order_id']]['side'].lower()
    )]
    if mismatches:
        raise ValueError('crosswalk symbol/side conflicts with archived ledger')
    match_count=sum(row['exact_order_id_match']=='MATCH' and row['pdf_trade_id_match']=='MATCH' and row['pdf_both_ledger_ids_match']=='MATCH' for row in records)
    gaps=[{'case':row['case'],'symbol_class':'ETH_MARGIN_CLOSE' if ':' in row['nija_symbol'] else 'SPOT_OR_OTHER',
           'csv_status':row['exact_order_id_match']}
          for row in records if row['exact_order_id_match']!='MATCH' or row['pdf_trade_id_match']!='MATCH' or row['pdf_both_ledger_ids_match']!='MATCH']
    # The CSV is operator-supplied; a positive text claim is never independently
    # authenticated by comparing it to the *same* historical archive.
    csv_claimed_auth=sum(row['broker_authenticated_account_scope']=='VERIFIED' for row in records)
    csv_claimed_basis=sum(row['opening_cost_basis_verified']=='VERIFIED' for row in records)
    csv_claimed_pnl=sum(row['realized_pnl_certified']=='VERIFIED' for row in records)
    return {
        'status':'HISTORICAL_FILES_STRUCTURALLY_CONSISTENT_BROKER_HISTORY_UNVERIFIED',
        'archive_sha256':hash_bytes(outer_raw),
        'recorded_archive_digest_matched':True,
        'crosswalk_sha256':hash_bytes(csv_raw),
        'sqlite_integrity':'ok',
        'isolated_restore_integrity':'ok',
        'nested_member_hashes_match':True,
        'sqlite_table_counts':counts,
        'account_position_json_files':len(positions),
        'entry_price_json_files':len(entry_prices),
        'archived_pending_kraken_orders':len(pending),
        'crosswalk_orders':len(records),
        'crosswalk_ids_equal_archive_ids':record_ids==set(by_id),
        'symbol_side_mismatch_cases':mismatches,
        'crosswalk_all_evidence_ids_matched':match_count,
        'crosswalk_missing_evidence_cases':gaps,
        'operator_csv_claimed_authenticated_records':csv_claimed_auth,
        'operator_csv_claimed_basis_verified_records':csv_claimed_basis,
        'operator_csv_claimed_pnl_certified_records':csv_claimed_pnl,
        'independently_authenticated_account_records':0,
        'independently_verified_opening_basis_records':0,
        'independently_certified_pnl_records':0,
        'scope':'historical_offhost_archive_only',
        'current_production_sqlite_integrity_verified':False,
        'historical_ledger_completeness_verified':False,
        'current_broker_positions_verified':False,
        'current_protective_exit_coverage_verified':False,
        'fresh_execution_proof_verified':False,
        'live_trading_authorized':False,
        'input_archives_modified':False,
    }


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--crosswalk',type=Path,required=True)
    p.add_argument('--expected-archive-sha256',required=True,
                   help='64-character digest recorded by the source host before off-host transfer')
    p.add_argument('--report',type=Path,default=None)
    args=p.parse_args()
    try:
        outcome=audit(args.archive,args.crosswalk,args.expected_archive_sha256)
    except (ValueError,KeyError,TypeError,tarfile.TarError,sqlite3.Error,OSError,UnicodeError,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'FAILED_CLOSED','reason':type(exc).__name__,
             'live_trading_authorized':False,'source_data_changed':False}))
        return 2
    result=json.dumps(outcome,indent=2,sort_keys=True)
    print(result)
    if args.report is not None:
        if args.report.exists() or args.report.is_symlink():
            raise SystemExit('Refusing to overwrite existing report')
        # Even the sanitized report should default to private permissions.
        mode = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(args.report, mode, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(result+'\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
