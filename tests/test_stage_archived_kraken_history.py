import importlib.util, io, json, os, pathlib, sqlite3, tarfile, tempfile, unittest
spec=importlib.util.spec_from_file_location('stage',str(pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'stage_archived_kraken_history.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class StagingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.out=self.root/'out';self.out.mkdir(mode=0o700);self.archive=self.root/'capture.tar.gz'
 def tearDown(self): self.tmp.cleanup()
 def capture(self,conflict=False,unsafe=False):
  with tarfile.open(self.archive,'w:gz') as t:
   for name,family,records in [('capture/07_trade_history_000.json','trades',{'T1':{'cost':'1.23','time':1}}),('capture/07_trade_history_001.json','trades',{'T1':{'cost':'9' if conflict else '1.23','time':1}}),('ledger/08_ledger_history_000.json','ledger',{'L1':{'amount':'1.23'}})]:
    body=json.dumps({'error':[],'result':{family:records,'count':1}}).encode();info=tarfile.TarInfo('../bad' if unsafe else name);info.size=len(body);t.addfile(info,io.BytesIO(body))
 def test_preservation_and_no_authority(self):
  self.capture();source=self.archive.read_bytes();result=m.stage_history(self.archive,self.out)
  self.assertEqual(result['unique_records'],{'trades':1,'ledger':1});self.assertEqual(result['duplicate_occurrences'],1)
  self.assertFalse(result['authorizes_orders']);self.assertFalse(result['production_ledger_changed']);self.assertEqual(source,self.archive.read_bytes())
  db=pathlib.Path(result['database']);self.assertEqual(db.stat().st_mode&0o777,0o600)
  with sqlite3.connect(db) as c:
   self.assertEqual(c.execute('select count(*) from archived_record').fetchone()[0],3)
   self.assertEqual(c.execute('select account_identity_verified,complete_history_verified,current_snapshot_verified,authorizes_orders from source_archive').fetchone(),(0,0,0,0))
   for body,digest in c.execute('select original_bytes,sha256 from source_page'):self.assertEqual(m.hashlib.sha256(body).hexdigest(),digest)
  second=m.stage_history(self.archive,self.out);self.assertNotEqual(second['database'],result['database'])
 def test_conflict_cleans_only_new_output(self):
  sentinel=self.out/'preserve';sentinel.write_text('existing');self.capture(conflict=True)
  with self.assertRaises(m.StagingDenied):m.stage_history(self.archive,self.out)
  self.assertEqual(list(self.out.iterdir()),[sentinel]);self.assertEqual(sentinel.read_text(),'existing')
 def test_path_traversal_rejected(self):
  self.capture(unsafe=True)
  with self.assertRaises(m.StagingDenied):m.stage_history(self.archive,self.out)
  self.assertEqual(list(self.out.iterdir()),[])
 def test_public_output_rejected(self):
  self.capture();self.out.chmod(0o755)
  with self.assertRaises(m.StagingDenied):m.stage_history(self.archive,self.out)
 def test_symlink_source_rejected(self):
  self.capture();link=self.root/'link';link.symlink_to(self.archive)
  with self.assertRaises(m.StagingDenied):m.stage_history(link,self.out)
 def test_duplicate_json_keys_rejected(self):
  with self.assertRaises(m.StagingDenied):json.loads('{"a":1,"a":2}',object_pairs_hook=m._unique)
if __name__=='__main__':unittest.main()
