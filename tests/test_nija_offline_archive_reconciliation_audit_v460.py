"""Synthetic evidence tests: no live exchange, production files or private records."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts import nija_offline_archive_reconciliation_audit_v460 as audit


def _tar_members(members):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w:gz') as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def _write_csv(path, *, order='EXIT-1', symbol='XXBTZUSD', side='sell',
               exact_match='MATCH', operator_claim='NOT_VERIFIED'):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(audit.REQUIRED_CSV))
        writer.writeheader()
        writer.writerow({
            'case':'1', 'nija_order_id':order, 'nija_symbol':symbol,
            'nija_side':side, 'exact_order_id_match':exact_match,
            'pdf_trade_id_match':exact_match,
            'pdf_both_ledger_ids_match':exact_match,
            'broker_authenticated_account_scope':operator_claim,
            'opening_cost_basis_verified':operator_claim,
            'realized_pnl_certified':operator_claim,
        })


def _fixture(tmp_path, *, symbol='XXBTZUSD', side='sell',
             csv_order='EXIT-1', csv_symbol=None, csv_side=None,
             exact_match='MATCH', operator_claim='NOT_VERIFIED',
             tamper_manifest=False, duplicate_manifest_key=False,
             traversal=False):
    sql = tmp_path / 'synthetic.db'
    with sqlite3.connect(sql) as conn:
        for name in audit.REQUIRED_TABLES:
            if name == 'pending_kraken_closes':
                conn.execute('''CREATE TABLE pending_kraken_closes
                  (order_id TEXT, symbol TEXT, side TEXT, broker TEXT,
                   account_scope TEXT, state TEXT, verification_level TEXT)''')
            else:
                conn.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO pending_kraken_closes VALUES (?,?,?,?,?,?,?)',
                     ('EXIT-1', symbol, side, 'kraken', 'platform:kraken',
                      'pending', 'unverified'))
    ledger = sql.read_bytes()
    tracked = {'trade_ledger.db': {
        'bytes':len(ledger), 'sha256':hashlib.sha256(ledger).hexdigest()}}
    if tamper_manifest:
        tracked['trade_ledger.db']['sha256'] = '0' * 64
    counts = {table: int(table == 'pending_kraken_closes')
              for table in audit.REQUIRED_TABLES}
    manifest = {'format_version':1, 'members':tracked, 'sqlite_tables':counts}
    manifest_raw = json.dumps(manifest).encode()
    if duplicate_manifest_key:
        manifest_raw = manifest_raw[:-1] + b',"format_version":1}'
    inner = _tar_members([
        ('trade_ledger.db', ledger),
        ('manifest.json', manifest_raw),
    ])
    members = [
        ('nija-trading-ledger-synthetic.tar.gz', inner),
        ('positions/platform__kraken.json', b'{"BTC-USD": {}}'),
        ('entry_prices/platform__kraken.json', b'{"BTC-USD": {}}'),
    ]
    if traversal:
        members.append(('../escape.json', b'{}'))
    archive_path = tmp_path / 'recovery.tar.gz'
    archive_path.write_bytes(_tar_members(members))
    csv_path = tmp_path / 'crosswalk.csv'
    _write_csv(csv_path, order=csv_order, symbol=csv_symbol or symbol,
               side=csv_side or side, exact_match=exact_match,
               operator_claim=operator_claim)
    sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return archive_path, csv_path, sha


def test_clean_synthetic_crosswalk_preserves_input_bytes_and_denies_trading(tmp_path):
    archive, csv_file, digest = _fixture(tmp_path)
    original = archive.read_bytes(), csv_file.read_bytes()
    result = audit.audit(archive, csv_file, digest)
    assert result['recorded_archive_digest_matched'] is True
    assert result['crosswalk_all_evidence_ids_matched'] == 1
    assert result['isolated_restore_integrity'] == 'ok'
    assert result['sqlite_integrity'] == 'ok'
    assert result['sqlite_table_counts']['pending_kraken_closes'] == 1
    assert result['current_production_sqlite_integrity_verified'] is False
    assert result['live_trading_authorized'] is False
    assert original == (archive.read_bytes(), csv_file.read_bytes())


def test_missing_margin_trade_fails_independent_broker_verification(tmp_path):
    archive, crosswalk, digest = _fixture(
        tmp_path, symbol='ETHUSD:BTNL', exact_match='NOT_FOUND')
    result = audit.audit(archive, crosswalk, digest)
    assert result['crosswalk_orders'] == 1
    assert result['crosswalk_all_evidence_ids_matched'] == 0
    assert result['crosswalk_missing_evidence_cases'] == [
        {'case': '1', 'symbol_class': 'ETH_MARGIN_CLOSE', 'csv_status': 'NOT_FOUND'}]
    assert result['independently_authenticated_account_records'] == 0
    assert result['independently_verified_opening_basis_records'] == 0
    assert result['live_trading_authorized'] is False


def test_claims_cannot_self_certify_opening_cost_basis_or_pnl(tmp_path):
    archive, crosswalk, digest = _fixture(tmp_path, operator_claim='VERIFIED')
    result = audit.audit(archive, crosswalk, digest)
    assert result['operator_csv_claimed_authenticated_records'] == 1
    assert result['operator_csv_claimed_basis_verified_records'] == 1
    assert result['operator_csv_claimed_pnl_certified_records'] == 1
    assert result['independently_authenticated_account_records'] == 0
    assert result['independently_verified_opening_basis_records'] == 0
    assert result['independently_certified_pnl_records'] == 0
    assert result['live_trading_authorized'] is False


@pytest.mark.parametrize('field,value', [
    ('csv_order', 'MISMATCH-OTHER-ORDER'),
    ('csv_symbol', 'OTHER-PAIR'),
    ('csv_side', 'buy'),
])
def test_csv_order_symbol_side_mismatch_is_rejected(tmp_path, field, value):
    archive, crosswalk, digest = _fixture(tmp_path, **{field: value})
    with pytest.raises(ValueError, match='crosswalk'):
        audit.audit(archive, crosswalk, digest)


def test_requires_exact_independently_recorded_archive_digest(tmp_path):
    archive, crosswalk, digest = _fixture(tmp_path)
    with pytest.raises(ValueError, match='historical_archive_source_digest_mismatch'):
        audit.audit(archive, crosswalk, '0' * 64)
    for invalid in ('', 'not-a-digest', 'g' * 64):
        with pytest.raises(ValueError, match='invalid_expected_archive_sha256'):
            audit.audit(archive, crosswalk, invalid)
    assert audit.audit(archive, crosswalk, digest.upper())['recorded_archive_digest_matched']


@pytest.mark.parametrize('change,expected', [
    ('tamper_manifest', 'nested file digest/size mismatch'),
    ('duplicate_manifest_key', 'duplicate_json_member_key'),
    ('traversal', 'unsafe archive member name'),
])
def test_archive_metadata_or_member_attack_rejected(tmp_path, change, expected):
    archive, crosswalk, digest = _fixture(tmp_path, **{change: True})
    with pytest.raises(ValueError, match=expected):
        audit.audit(archive, crosswalk, digest)
    assert not (tmp_path.parent / 'escape.json').exists()


def test_symlink_archive_rejected_without_following(tmp_path):
    archive, crosswalk, digest = _fixture(tmp_path)
    symlink = tmp_path / 'symlink.tar.gz'
    symlink.symlink_to(archive)
    with pytest.raises(OSError):
        audit.audit(symlink, crosswalk, digest)


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='requires POSIX FIFO')
def test_fifo_never_blocks_input_reader(tmp_path):
    pipe = tmp_path / 'fake.csv'
    os.mkfifo(pipe)
    with pytest.raises(ValueError, match='input_not_regular_file'):
        audit._pinned_read_file(pipe, 4096)


def test_duplicate_crosswalk_ids_fail_closed(tmp_path):
    archive, crosswalk, digest = _fixture(tmp_path)
    with crosswalk.open('a', encoding='utf-8') as stream:
        stream.write('1,EXIT-1,XXBTZUSD,sell,MATCH,MATCH,MATCH,NOT_VERIFIED,NOT_VERIFIED,NOT_VERIFIED\n')
    with pytest.raises(ValueError, match='duplicate'):
        audit.audit(archive, crosswalk, digest)


def test_report_is_private_and_never_overwritten(tmp_path):
    archive, crosswalk, digest = _fixture(tmp_path)
    report = tmp_path / 'summary.json'
    script = Path(audit.__file__).resolve()
    cmd = [sys.executable, '-S', str(script), '--archive', str(archive),
           '--crosswalk', str(crosswalk), '--expected-archive-sha256', digest,
           '--report', str(report)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['live_trading_authorized'] is False
    assert report.exists()
    assert report.stat().st_mode & 0o777 == 0o600
    before = report.read_bytes()
    again = subprocess.run(cmd, text=True, capture_output=True)
    assert again.returncode != 0
    assert report.read_bytes() == before
