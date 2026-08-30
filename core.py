from __future__ import annotations
import hashlib,json,logging,os,re,shutil,sqlite3,subprocess,threading,time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,time as dtime,timedelta,timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo
try:
 from dotenv import load_dotenv
except ImportError:
 def load_dotenv(*args,**kwargs): return False
from integration import FolderResolver
BASE=Path(__file__).resolve().parent
def _choose_state_base():
 candidates=[]
 if os.getenv('PM_STATE_DIR'):candidates.append(Path(os.getenv('PM_STATE_DIR')))
 if os.getenv('LOCALAPPDATA'):candidates.append(Path(os.getenv('LOCALAPPDATA'))/'PublicationManager')
 if os.getenv('TEMP') or os.getenv('TMP'):candidates.append(Path(os.getenv('TEMP') or os.getenv('TMP'))/'PublicationManager')
 candidates.append(BASE)
 for candidate in candidates:
  try:candidate.mkdir(parents=True,exist_ok=True);return candidate
  except OSError:continue
 return BASE
STATE_BASE=_choose_state_base()
DEFAULT={"auto_video_cutter":{"project_dir":"","input_dir":"","output_dir":"","linked":True},"output_dir":"","timezone":"America/Sao_Paulo","publication_times":["12:45","19:30"],"first_publication":{"mode":"tomorrow","time":"12:45","custom_datetime":""},"missed_policy":"reschedule","stable_seconds":10,"scan_interval_seconds":3,"ffprobe_timeout_seconds":20,"retry_delays_minutes":[5,15,60,180],"test_mode":True,"real_publication_confirmed":False,"auto_monitor":True,"start_with_windows":False,"insights_monitor":True,"insights_interval_minutes":30,"platforms":{"facebook_reels":False,"instagram_reels":False},"captions":{"facebook":{"hashtags":"#reels #facebookreels #viral #carrosel #novelas #novela","follow":"Siga @passaproladoofc para mais"},"instagram":{"hashtags":"#reels #instagramreels #viral #carrosel #novelas #novela","follow":"Siga @passaproladoofc para mais"}},"meta":{"graph_version":"v26.0","facebook_page_id":"","facebook_page_name":"","instagram_user_id":"","instagram_username":"","connected_user_id":"","connected_user_name":"","token_expires_at":0,"available_pages":[],"share_instagram_reel_to_feed":True}}
def utcnow():return datetime.now(timezone.utc).isoformat()
def normpath(p):return os.path.normcase(os.path.abspath(str(p)))
class Config:
 def __init__(self,path=None):
  load_dotenv(BASE/'.env');self.path=Path(path or os.getenv('PM_CONFIG_FILE') or STATE_BASE/'config.json');self.data=deepcopy(DEFAULT)
  seed=BASE/'config.json'
  source=self.path if self.path.exists() else seed if seed.exists() else None
  if source:self.merge(self.data,json.loads(source.read_text(encoding='utf-8-sig')))
  # This installation targets Instagram only; never inherit a stale Facebook toggle.
  self.data['platforms']['facebook_reels']=False
  self.data['platforms']['instagram_reels']=True
  self.validate()
 @staticmethod
 def merge(a,b):
  for k,v in b.items():Config.merge(a[k],v) if isinstance(v,dict) and isinstance(a.get(k),dict) else a.__setitem__(k,v)
 def validate(self):
  ZoneInfo(self.data['timezone']);times=[]
  for s in self.data['publication_times']:
   h,m=map(int,s.split(':'))
   if not(0<=h<24 and 0<=m<60):raise ValueError('Horário inválido: '+s)
   times.append(f'{h:02d}:{m:02d}')
  if not times:raise ValueError('Configure ao menos um horário.')
  self.data['publication_times']=sorted(set(times))
  if self.data['missed_policy'] not in ('skip','reschedule'):raise ValueError('Política de horário perdido inválida.')
  if self.data['first_publication']['mode'] not in ('next','tomorrow','custom'):raise ValueError('Regra da primeira publicação inválida.')
 def save(self):self.validate();self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')
 @property
 def tz(self):return ZoneInfo(self.data['timezone'])
 @property
 def folder(self):
  p=self.data.get('output_dir') or self.data['auto_video_cutter'].get('output_dir','')
  return Path(p).expanduser() if p else Path()
 def set_integration(self,info):
  self.data['auto_video_cutter'].update(info);self.data['output_dir']=info['output_dir'];self.save()
 def refresh_integration(self):
  a=self.data['auto_video_cutter'];project=a.get('project_dir')
  if project and a.get('linked',True):self.set_integration(FolderResolver(BASE).inspect(project))
class DB:
 def __init__(self,path=None):
  self.path=Path(path or STATE_BASE/'data/database.sqlite');self.path.parent.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.init()
 @contextmanager
 def con(self):
  with self.lock:
   c=sqlite3.connect(self.path,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=30000')
   try:yield c;c.commit()
   except:c.rollback();raise
   finally:c.close()
 def init(self):
  schema="""CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY,fingerprint TEXT,hash TEXT NOT NULL,nome TEXT NOT NULL,caminho TEXT NOT NULL,normalized_path TEXT,size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,capitulo INTEGER NOT NULL,parte INTEGER NOT NULL,ordem INTEGER NOT NULL DEFAULT 0,arquivo_mp4 TEXT NOT NULL,arquivo_txt TEXT NOT NULL,arquivo_srt TEXT,metadata_json TEXT,legenda TEXT NOT NULL,status TEXT NOT NULL,data_detectado TEXT NOT NULL,data_agendada TEXT,id_publicacao TEXT,erro TEXT,tentativas INTEGER NOT NULL DEFAULT 0,tentar_apos TEXT,atualizado_em TEXT NOT NULL)"""
  with self.con() as c:
   existing=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='videos'").fetchone()
   legacy=existing and ('hash TEXT NOT NULL UNIQUE' in (existing['sql'] or '') or 'caminho TEXT NOT NULL UNIQUE' in (existing['sql'] or ''))
   if legacy:
    c.execute('ALTER TABLE videos RENAME TO videos_legacy');c.execute(schema)
    old={r['name'] for r in c.execute('PRAGMA table_info(videos_legacy)')};newcols={r['name'] for r in c.execute('PRAGMA table_info(videos)')};common=[x for x in old & newcols if x!='fingerprint']
    cols=','.join(common);c.execute(f'INSERT INTO videos({cols}) SELECT {cols} FROM videos_legacy');c.execute("UPDATE videos SET fingerprint=hash||':'||id,normalized_path=LOWER(caminho)");c.execute('DROP TABLE videos_legacy')
   else:c.execute(schema)
   cols={r['name'] for r in c.execute('PRAGMA table_info(videos)')}
   for name,definition in {'fingerprint':'TEXT','normalized_path':'TEXT','size':'INTEGER NOT NULL DEFAULT 0','mtime_ns':'INTEGER NOT NULL DEFAULT 0','ordem':'INTEGER NOT NULL DEFAULT 0','arquivo_srt':'TEXT','metadata_json':'TEXT'}.items():
    if name not in cols:c.execute(f'ALTER TABLE videos ADD COLUMN {name} {definition}')
   c.execute("UPDATE videos SET fingerprint=COALESCE(fingerprint,hash||':'||id),normalized_path=COALESCE(normalized_path,LOWER(caminho))")
   c.execute('CREATE INDEX IF NOT EXISTS idx_queue ON videos(status,data_agendada)');c.execute('CREATE INDEX IF NOT EXISTS idx_path_signature ON videos(normalized_path,size,mtime_ns)');c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_fingerprint ON videos(fingerprint)')
   c.execute('''CREATE TABLE IF NOT EXISTS insights(id INTEGER PRIMARY KEY,video_id INTEGER,platform TEXT NOT NULL,remote_id TEXT NOT NULL,fetched_at TEXT NOT NULL,metrics_json TEXT NOT NULL,permalink TEXT,error TEXT)''')
   c.execute('CREATE INDEX IF NOT EXISTS idx_insights_video ON insights(video_id,platform,fetched_at)')
 def add(self,x):
  n=utcnow()
  with self.con() as c:
   exists=c.execute('SELECT 1 FROM videos WHERE fingerprint=? OR (normalized_path=? AND size=? AND mtime_ns=?)',(x['fingerprint'],x['normalized_path'],x['size'],x['mtime_ns'])).fetchone()
   if exists:return False
   c.execute('''INSERT INTO videos(fingerprint,hash,nome,caminho,normalized_path,size,mtime_ns,capitulo,parte,ordem,arquivo_mp4,arquivo_txt,arquivo_srt,metadata_json,legenda,status,data_detectado,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDENTE',?,?)''',(x['fingerprint'],x['hash'],x['nome'],x['caminho'],x['normalized_path'],x['size'],x['mtime_ns'],x['capitulo'],x['parte'],x['ordem'],x['arquivo_mp4'],x['arquivo_txt'],x.get('arquivo_srt'),x.get('metadata_json'),x['legenda'],n,n));return True
 def all(self):
  with self.con() as c:return [dict(r) for r in c.execute('SELECT * FROM videos ORDER BY CASE WHEN data_agendada IS NULL THEN 1 ELSE 0 END,data_agendada,ordem,capitulo,parte,id')]
 def stats(self):
  with self.con() as c:d={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM videos GROUP BY status')}
  return {'total':sum(d.values()),'pending':d.get('PENDENTE',0)+d.get('ERRO',0),'scheduled':d.get('AGENDADO',0),'published':d.get('PUBLICADO',0)+d.get('SIMULADO',0),'errors':d.get('ERRO',0)+d.get('REVISAO',0)}
 def schedule(self,pairs):
  if not pairs:return
  with self.con() as c:c.executemany("UPDATE videos SET data_agendada=?,status='AGENDADO',erro=NULL,tentar_apos=NULL,atualizado_em=? WHERE id=?",[(dt,utcnow(),i) for i,dt in pairs])
 def due(self,now=None):
  now=now or utcnow()
  with self.con() as c:return [dict(r) for r in c.execute("SELECT * FROM videos WHERE status='AGENDADO' AND data_agendada<=? AND (tentar_apos IS NULL OR tentar_apos<=?) ORDER BY data_agendada",(now,now))]
 def missed(self,now):
  with self.con() as c:return [dict(r) for r in c.execute("SELECT * FROM videos WHERE status='AGENDADO' AND data_agendada<? ORDER BY data_agendada",(now,))]
 def unschedule(self,ids,message,status='PENDENTE'):
  if not ids:return
  q=','.join('?'*len(ids))
  with self.con() as c:c.execute(f"UPDATE videos SET status=?,data_agendada=NULL,erro=?,atualizado_em=? WHERE id IN ({q})",(status,message,utcnow(),*ids))
 def claim(self,i):
  with self.con() as c:return c.execute("UPDATE videos SET status='PUBLICANDO',atualizado_em=? WHERE id=? AND status='AGENDADO'",(utcnow(),i)).rowcount==1
 def result(self,i,status,ids=None,error=None,retry=None,attempt=False):
  with self.con() as c:c.execute('UPDATE videos SET status=?,id_publicacao=COALESCE(?,id_publicacao),erro=?,tentar_apos=?,tentativas=tentativas+?,atualizado_em=? WHERE id=?',(status,json.dumps(ids,ensure_ascii=False) if ids else None,error,retry,1 if attempt else 0,utcnow(),i))
 def recover(self):
  with self.con() as c:return c.execute("UPDATE videos SET status='REVISAO',erro='Publicação interrompida. Confira na Meta antes de repetir.',atualizado_em=? WHERE status='PUBLICANDO'",(utcnow(),)).rowcount

 def save_insight(self,video_id,platform,remote_id,metrics,permalink=None,error=None):
  with self.con() as c:c.execute('INSERT INTO insights(video_id,platform,remote_id,fetched_at,metrics_json,permalink,error) VALUES(?,?,?,?,?,?,?)',(video_id,platform,remote_id,utcnow(),json.dumps(metrics or {},ensure_ascii=False),permalink,error))
 def latest_insights(self,limit=500):
  with self.con() as c:return [dict(r) for r in c.execute('SELECT * FROM insights ORDER BY fetched_at DESC LIMIT ?',(int(limit),))]
 def insight_summary(self):
  rows=self.latest_insights();totals={};last=''
  for r in rows:
   if not last or r['fetched_at']>last:last=r['fetched_at']
   try:m=json.loads(r['metrics_json'])
   except (TypeError,ValueError):m={}
   for k,v in m.items():
    if isinstance(v,(int,float)):totals[k]=totals.get(k,0)+v
  return {'samples':len(rows),'last_fetched_at':last,'totals':totals}

def logger():
 l=logging.getLogger('pm');l.setLevel(logging.INFO)
 if not l.handlers:
  formatter=logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
  candidates=[Path(os.getenv('PM_LOG_FILE',''))] if os.getenv('PM_LOG_FILE') else []
  candidates += [BASE/'logs/publication_manager.log']
  local=os.getenv('LOCALAPPDATA')
  if local:candidates.append(Path(local)/'PublicationManager'/'publication_manager.log')
  for target in candidates:
   if not str(target):continue
   try:
    target.parent.mkdir(parents=True,exist_ok=True)
    h=RotatingFileHandler(target,maxBytes=2_000_000,backupCount=5,encoding='utf-8');h.setFormatter(formatter);l.addHandler(h);break
   except (OSError,PermissionError):continue
  if not l.handlers:
   h=logging.StreamHandler();h.setFormatter(formatter);l.addHandler(h)
 return l
NUM=re.compile(r'(\d+)')
def number(s):
 m=NUM.search(str(s));return int(m.group(1)) if m else 0
class Scanner:
 def __init__(self,cfg,db,log,changed=lambda:None,on_added=lambda n:None,probe=None):self.cfg=cfg;self.db=db;self.log=log;self.changed=changed;self.on_added=on_added;self.probe=probe or self._ffprobe;self.seen={};self.stop=threading.Event();self.thread=None
 def start(self):
  if self.thread and self.thread.is_alive():return
  self.stop.clear();self.thread=threading.Thread(target=self.loop,daemon=True,name='scanner');self.thread.start()
 def halt(self):self.stop.set()
 def stable(self,p):
  try:s=p.stat();f=open(p,'rb');f.read(1);f.close()
  except OSError:return False
  k=normpath(p);sig=(s.st_size,s.st_mtime_ns);old=self.seen.get(k);now=time.monotonic()
  if not old or old[0]!=sig:self.seen[k]=(sig,now);return False
  return s.st_size>0 and now-old[1]>=float(self.cfg.data['stable_seconds'])
 def _ffprobe(self,p):
  exe=shutil.which('ffprobe')
  if not exe:return False
  try:
   r=subprocess.run([exe,'-v','error','-select_streams','v:0','-show_entries','stream=codec_type,duration','-of','json',str(p)],capture_output=True,text=True,timeout=self.cfg.data['ffprobe_timeout_seconds'])
   return r.returncode==0 and bool(json.loads(r.stdout or '{}').get('streams'))
  except (OSError,subprocess.SubprocessError,ValueError):return False
 def _metadata(self,mp4,root):
  for parent in (mp4.parent,*mp4.parents):
   if parent==root.parent:break
   f=parent/'metadata.json'
   if f.exists():
    try:return f,json.loads(f.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return f,{}
  return None,{}
 @staticmethod
 def _match_part(meta,mp4):
  target=normpath(mp4)
  for i,p in enumerate(meta.get('parts',[]) if isinstance(meta,dict) else []):
   vals=[p.get(k) for k in ('path','mp4','arquivo_mp4','video_path','video_file','output')]
   if any(v and (normpath(v)==target or Path(v).name.casefold()==mp4.name.casefold()) for v in vals):return i,p
  return -1,{}
 def make_item(self,mp4,txt,root):
  stat=mp4.stat();mf,meta=self._metadata(mp4,root);idx,part=self._match_part(meta,mp4)
  ch=number(part.get('chapter') or part.get('chapter_number') or mp4.parent.name);pt=number(part.get('part') or part.get('part_number') or mp4.stem);order=int(part.get('order',idx if idx>=0 else ch*10000+pt));video=meta.get('video',{}) if isinstance(meta,dict) else {};title=part.get('title') or part.get('chapter_title') or f'CAPÍTULO {ch:02d} - PARTE {pt:02d}'
  try:caption=txt.read_text(encoding='utf-8-sig')
  except UnicodeDecodeError:caption=txt.read_text(encoding='cp1252')
  h=hashlib.sha256()
  with mp4.open('rb') as f:
   for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
  digest=h.hexdigest();fingerprint=hashlib.sha256(f'{normpath(mp4)}|{digest}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8')).hexdigest()
  return {'fingerprint':fingerprint,'hash':digest,'nome':title,'caminho':str(mp4.resolve()),'normalized_path':normpath(mp4),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'capitulo':ch,'parte':pt,'ordem':order,'arquivo_mp4':str(mp4.resolve()),'arquivo_txt':str(txt.resolve()),'arquivo_srt':str(mp4.with_suffix('.srt').resolve()) if mp4.with_suffix('.srt').exists() else None,'metadata_json':str(mf.resolve()) if mf else None,'legenda':caption}
 def scan(self):
  root=self.cfg.folder
  if not str(root) or not root.exists():self.log.warning('[SCANNER] Pasta não existe: %s',root);return 0
  added=0
  for mp4 in sorted(root.rglob('*.mp4'),key=lambda p:(number(p.parent.name),number(p.stem),str(p).casefold())):
   txt=mp4.with_suffix('.txt')
   if not txt.exists():continue
   mp4_ok=self.stable(mp4);txt_ok=self.stable(txt)
   if not (mp4_ok and txt_ok):continue
   if not self.probe(mp4):self.log.warning('[VALIDAÇÃO] FFprobe rejeitou %s',mp4);continue
   x=self.make_item(mp4,txt,root)
   if self.db.add(x):added+=1;self.log.info('[SCANNER] Novo vídeo detectado: %s',mp4.relative_to(root));self.log.info('[VALIDAÇÃO] MP4 estável; TXT encontrado');self.log.info('[FILA] Adicionado: %s',x['nome'])
  if added:self.on_added(added);self.changed()
  return added
 def loop(self):
  while not self.stop.is_set():
   try:self.scan()
   except Exception:self.log.exception('[SCANNER] Falha')
   self.stop.wait(self.cfg.data['scan_interval_seconds'])
class Queue:
 def __init__(self,cfg,db,log=None,now_fn=None):self.cfg=cfg;self.db=db;self.log=log or logger();self.now_fn=now_fn or (lambda:datetime.now(self.cfg.tz))
 def _floor(self,now):
  f=self.cfg.data['first_publication'];mode=f['mode']
  if mode=='tomorrow':
   h,m=map(int,(f.get('time') or self.cfg.data['publication_times'][0]).split(':'));return datetime.combine(now.date()+timedelta(days=1),dtime(h,m),tzinfo=self.cfg.tz)
  if mode=='custom' and f.get('custom_datetime'):
   x=datetime.fromisoformat(f['custom_datetime']);return x.replace(tzinfo=self.cfg.tz) if x.tzinfo is None else x.astimezone(self.cfg.tz)
  return now
 def fill(self):
  rows=self.db.all();todo=[r for r in rows if r['status'] in ('PENDENTE','ERRO') and not r['data_agendada']]
  if not todo:return 0
  todo.sort(key=lambda r:(r.get('ordem',0),r['capitulo'],r['parte'],r['id']))
  occupied={datetime.fromisoformat(r['data_agendada']).astimezone(self.cfg.tz) for r in rows if r['data_agendada']}
  now=self.now_fn();floor=max(now,self._floor(now)) if not occupied else now;day=floor.date();slots=[]
  while len(slots)<len(todo):
   for s in self.cfg.data['publication_times']:
    h,m=map(int,s.split(':'));slot=datetime.combine(day,dtime(h,m),tzinfo=self.cfg.tz)
    if slot>=floor and slot>now and slot not in occupied:slots.append(slot)
    if len(slots)==len(todo):break
   day+=timedelta(days=1)
  pairs=[(r['id'],s.astimezone(timezone.utc).isoformat()) for r,s in zip(todo,slots)];self.db.schedule(pairs)
  for r,s in zip(todo,slots):self.log.info('[SCHEDULER] %s agendado para %s',r['nome'],s.strftime('%d/%m/%Y %H:%M'))
  return len(pairs)
 def recover_missed(self,now=None):
  now=now or self.now_fn();rows=self.db.missed(now.astimezone(timezone.utc).isoformat())
  if not rows:return 0
  msg='Publicação perdida enquanto o programa estava desligado.';ids=[r['id'] for r in rows]
  if self.cfg.data['missed_policy']=='skip':self.db.unschedule(ids,msg,'PERDIDO');return len(ids)
  self.db.unschedule(ids,msg,'PENDENTE');self.fill();return len(ids)
