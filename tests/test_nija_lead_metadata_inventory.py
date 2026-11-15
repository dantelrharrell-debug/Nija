"""Synthetic safety checks for metadata-only lead inventory."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.nija_lead_metadata_inventory import inventory, metadata


class MetadataInventoryTests(unittest.TestCase):
    def test_no_sqlite_or_content_reads_and_no_file_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lead = root / 'old_leads.sqlite3'
            lead.write_bytes(b'not even SQLite; metadata must still work')
            wal = Path(str(lead) + '-wal')
            wal.write_bytes(b'unread WAL')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with patch('sqlite3.connect', side_effect=AssertionError('no SQLite')), \
                    patch.object(Path, 'open', side_effect=AssertionError('no content reads')):
                report = inventory({'NIJA_LEAD_DB_PATH': str(lead)}, root, root / 'missing')
            after = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(before, after)
            self.assertFalse(report['production_certified'])
            self.assertFalse(report['sqlite_opened'])
            found = next(x for x in report['candidates'] if x['path'] == str(lead))
            self.assertEqual(found['size_bytes'], len(before[lead.name]))
            self.assertEqual(found['sidecars'][0]['status'], 'METADATA_ONLY')
            self.assertTrue(any(x['reason'] == 'missing_not_zero_records'
                                for x in found['sidecars'][1:]))

    def test_invalid_override_never_leaks_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = inventory({'NIJA_LEAD_DB_PATH': '../PRIVATE',
                                'NIJA_OUTREACH_DB_PATH': '   ', 'UNRELATED_SETTING': 'HIDDEN'}, root, root)
            encoded = json.dumps(report)
            self.assertNotIn('PRIVATE', encoded)
            self.assertNotIn('HIDDEN', encoded)
            self.assertEqual(report['lead_path_overrides']['NIJA_LEAD_DB_PATH']['status'],
                             'invalid_or_redacted_path')

    def test_symlink_file_and_parent_are_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'target'
            target.mkdir()
            source = target / 'leads.db'
            source.write_bytes(b'private')
            link = root / 'alias'
            link.symlink_to(target, target_is_directory=True)
            result = metadata(link / 'leads.db', root)
            self.assertEqual(result['reason'], 'symlink_requires_owner_review')
            self.assertNotIn('size_bytes', result)

    def test_candidate_discovery_does_not_recurse_into_trading_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root / 'trading'
            private.mkdir()
            (private / 'lead_named.db').write_bytes(b'private')
            report = inventory({}, root, root / 'missing')
            self.assertNotIn('lead_named.db', json.dumps(report))
            self.assertEqual(report['discovery'][str(root)], 'top_level_only')


if __name__ == '__main__':
    unittest.main()
