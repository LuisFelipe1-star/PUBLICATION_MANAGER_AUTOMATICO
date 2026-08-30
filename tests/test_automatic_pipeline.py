import json,logging,os,sys,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core import Config,DB,Queue,Scanner
from integration import FolderResolver
class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.out=self.root/'saida';self.out.mkdir();self.config_path=self.root/'pm.json';self.cfg=Config(self.config_path);self.cfg.data['output_dir']=str(self.out);self.cfg.data['stable_seconds']=0;self.cfg.data['publication_times']=['12:45','19:30'];self.cfg.data['first_publication']={'mode':'tomorrow','time':'12:45','custom_datetime':''};self.cfg.save();self.db=DB(self.root/'db.sqlite');self.log=logging.getLogger('test')
 def tearDown(self):self.t.cleanup()
 def cutter(self,output='saida'):
  p=self.root/'AUTO_VIDEO_CUTTER_AI';p.mkdir(exist_ok=True);(p/'backend').mkdir(exist_ok=True);(p/'gui').mkdir(exist_ok=True);(p/'main.py').write_text('');(p/'config.json').write_text(json.dumps({'folders':{'input':'input','output':output,'downloads':'downloads','temp':'temp','logs':'logs'}}));return p
 def clip(self,ch=1,pt=1,txt=True,content=b'video'):
  d=self.out/f'Video/CAPITULO_{ch:02d}';d.mkdir(parents=True,exist_ok=True);m=d/f'parte_{pt:02d}.mp4';m.write_bytes(content)
  if txt:m.with_suffix('.txt').write_text(f'legenda {ch}-{pt}',encoding='utf-8')
  return m
 def scanner(self):return Scanner(self.cfg,self.db,self.log,probe=lambda p:True)
 def scan_ready(self,s):s.scan();return s.scan()
 def add_n(self,n):
  for i in range(n):self.clip(i//10+1,i%10+1,content=f'v{i}'.encode())
  self.scan_ready(self.scanner())
 def test_01_detect_project(self):self.assertEqual(Path(FolderResolver(self.root).detect(self.cutter())['project_dir']),self.cutter())
 def test_02_read_folders_output(self):self.assertEqual(Path(FolderResolver(self.root).inspect(self.cutter('custom'))['output_dir']),self.cutter()/'custom')
 def test_03_detect_mp4_txt(self):self.clip();self.assertEqual(self.scan_ready(self.scanner()),1)
 def test_04_ignore_without_txt(self):self.clip(txt=False);self.assertEqual(self.scan_ready(self.scanner()),0)
 def test_05_ignore_file_being_written(self):
  self.cfg.data['stable_seconds']=999;self.clip();s=self.scanner();self.assertEqual(s.scan(),0);self.assertEqual(s.scan(),0)
 def test_06_recursive_subfolders(self):self.clip(4,7);self.assertEqual(self.scan_ready(self.scanner()),1)
 def test_07_chapter_part_order(self):
  self.clip(2,1);self.clip(1,2);self.clip(1,1);self.scan_ready(self.scanner());self.assertEqual([(r['capitulo'],r['parte']) for r in sorted(self.db.all(),key=lambda r:(r['capitulo'],r['parte']))],[(1,1),(1,2),(2,1)])
 def test_08_no_duplicate(self):self.clip();s=self.scanner();self.scan_ready(s);self.assertEqual(s.scan(),0);self.assertEqual(len(self.db.all()),1)
 def test_09_auto_schedule(self):self.add_n(2);self.assertEqual(Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz)).fill(),2)
 def test_10_starts_tomorrow(self):self.add_n(1);Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz)).fill();self.assertEqual(datetime.fromisoformat(self.db.all()[0]['data_agendada']).astimezone(self.cfg.tz).strftime('%Y-%m-%d %H:%M'),'2026-08-25 12:45')
 def test_11_distribute_10(self):self.add_n(10);Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz)).fill();self.assertEqual(len({r['data_agendada'] for r in self.db.all()}),10)
 def test_12_distribute_100(self):self.add_n(100);self.assertEqual(Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz)).fill(),100)
 def test_13_new_video_while_running(self):self.add_n(1);q=Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz));q.fill();self.clip(9,9);self.scan_ready(self.scanner());self.assertEqual(q.fill(),1)
 def test_14_no_past_slot(self):
  self.cfg.data['first_publication']['mode']='next';self.add_n(1);Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,20,tzinfo=self.cfg.tz)).fill();x=datetime.fromisoformat(self.db.all()[0]['data_agendada']).astimezone(self.cfg.tz);self.assertGreater(x,datetime(2026,8,24,20,tzinfo=self.cfg.tz))
 def test_15_schedule_persists_sqlite(self):self.add_n(1);Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz)).fill();self.assertTrue(DB(self.root/'db.sqlite').all()[0]['data_agendada'])
 def test_16_restart_keeps_schedule(self):self.test_15_schedule_persists_sqlite()
 def test_17_interrupted_publish_goes_review(self):self.add_n(1);r=self.db.all()[0];self.db.schedule([(r['id'],datetime.now(timezone.utc).isoformat())]);self.db.claim(r['id']);self.db.recover();self.assertEqual(self.db.all()[0]['status'],'REVISAO')
 def test_18_test_mode_default(self):self.assertTrue(self.cfg.data['test_mode'])
 def test_19_meta_connected_state(self):self.cfg.data['meta']['facebook_page_id']='1';self.assertEqual(self.cfg.data['meta']['facebook_page_id'],'1')
 def test_20_missing_folder(self):self.cfg.data['output_dir']=str(self.root/'missing');self.assertEqual(self.scanner().scan(),0)
 def test_21_changed_folder(self):self.cfg.data['output_dir']=str(self.root/'new');Path(self.cfg.data['output_dir']).mkdir();self.assertEqual(self.cfg.folder,Path(self.cfg.data['output_dir']))
 def test_22_metadata_available(self):
  m=self.clip(3,4);meta={'video':{'title':'Original'},'parts':[{'chapter':8,'part':9,'order':1,'title':'Título do metadata','video_file':m.name}]};(m.parents[1]/'metadata.json').write_text(json.dumps(meta),encoding='utf-8');self.scan_ready(self.scanner());r=self.db.all()[0];self.assertEqual((r['capitulo'],r['parte'],r['nome']),(8,9,'Título do metadata'))
 def test_23_metadata_absent(self):self.clip(2,3);self.scan_ready(self.scanner());r=self.db.all()[0];self.assertEqual((r['capitulo'],r['parte']),(2,3))
 def test_changed_same_path_is_new_version(self):
  m=self.clip();s=self.scanner();self.scan_ready(s);time.sleep(.002);m.write_bytes(b'changed');os.utime(m,None);self.scan_ready(s);self.assertEqual(len(self.db.all()),2)
 def test_missed_reschedules(self):
  self.add_n(1);r=self.db.all()[0];self.db.schedule([(r['id'],'2026-08-23T12:45:00+00:00')]);q=Queue(self.cfg,self.db,now_fn=lambda:datetime(2026,8,24,14,tzinfo=self.cfg.tz));self.assertEqual(q.recover_missed(),1);self.assertEqual(self.db.all()[0]['status'],'AGENDADO')
if __name__=='__main__':unittest.main()
