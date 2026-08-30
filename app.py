import json,os,re,sys,threading,tkinter as tk
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tkinter import filedialog,messagebox,ttk
from core import BASE,Config,DB,Scanner,Queue,logger
from integration import FolderResolver
from meta_api import MetaAPI,MetaError
from meta_auth import MetaOAuth
class Publisher:
 def __init__(self,cfg,db,log,changed):self.cfg=cfg;self.db=db;self.log=log;self.changed=changed;self.api=MetaAPI(cfg,lambda i,x:db.result(i,'PUBLICANDO',x))
 def caption(self,row,platform):
  base=(row.get('legenda') or '').strip()
  extras=self.cfg.data.get('captions',{}).get(platform,{})
  defaults='#reels #facebookreels #viral #carrosel #novelas #novela' if platform=='facebook' else '#reels #instagramreels #viral #carrosel #novelas #novela'
  configured=extras.get('hashtags') or defaults
  present={tag.casefold() for tag in re.findall(r'#[\\wÀ-ÿ]+',base,re.UNICODE)}
  selected=[]
  for tag in re.findall(r'#[\\wÀ-ÿ]+',configured,re.UNICODE):
   key=tag.casefold()
   if key not in present and key not in {x.casefold() for x in selected}:selected.append(tag)
  hashtags=' '.join(selected)
  follow=extras.get('follow') or 'Siga @passaproladoofc para mais'
  if '@passaproladoofc' in base.casefold():follow=''
  return '\n\n'.join(x for x in (base,hashtags,follow) if x)
 def publish(self,r):
  if not self.db.claim(r['id']):return
  self.log.info('[PUBLISHER] Iniciando publicação: %s',r['nome'])
  try:
   if self.cfg.data['test_mode']:self.db.result(r['id'],'SIMULADO',{'test_mode':True});return
   if not self.cfg.data.get('real_publication_confirmed'):raise MetaError('Publicação real ainda não foi confirmada.')
   p=self.cfg.data['platforms'];ids={}
   if not any(p.values()):raise MetaError('Nenhuma plataforma habilitada.')
   existing={}
   try: existing=json.loads(r.get('id_publicacao') or '{}')
   except (TypeError,ValueError): pass
   if p['facebook_reels'] and not existing.get('facebook_video_id'):
    ids.update(self.api.facebook(r,description=self.caption(r,'facebook')));self.log.info('[META] Facebook publicado')
   elif existing.get('facebook_video_id'):
    ids.update({k:v for k,v in existing.items() if k.startswith('facebook_')})
   if p['instagram_reels']:
    ids.update(self.api.instagram(r,caption=self.caption(r,'instagram')));self.log.info('[META] Instagram publicado')
   self.db.result(r['id'],'PUBLICADO',ids)
  except MetaError as e:
   n=r['tentativas']+1;ds=self.cfg.data['retry_delays_minutes'];status='REVISAO' if e.uncertain else ('AGENDADO' if e.transient and n<=len(ds) else 'ERRO');retry=(datetime.now(timezone.utc)+timedelta(minutes=ds[n-1])).isoformat() if status=='AGENDADO' else None;self.db.result(r['id'],status,error=str(e),retry=retry,attempt=True);self.log.error('[META] %s',e)
  except Exception as e:self.log.exception('[PUBLISHER] Falha inesperada');self.db.result(r['id'],'REVISAO',error=str(e),attempt=True)
  finally:self.changed()
 def prepare_remote(self,r):
  """Upload and schedule Facebook content before the local due time."""
  if self.cfg.data['test_mode'] or not self.cfg.data.get('real_publication_confirmed'): return
  if not self.cfg.data['platforms'].get('facebook_reels') or not r.get('data_agendada'): return
  try:
   existing=json.loads(r.get('id_publicacao') or '{}')
  except (TypeError,ValueError): existing={}
  if existing.get('facebook_video_id') or not self.db.claim(r['id']): return
  try:
   at=datetime.fromisoformat(r['data_agendada'])
   ids=self.api.facebook(r,scheduled_at=at,description=self.caption(r,'facebook'))
   status='AGENDADO' if self.cfg.data['platforms'].get('instagram_reels') else 'PUBLICADO'
   self.db.result(r['id'],status,ids)
   self.log.info('[META] Facebook enviado e agendado: %s',r['nome'])
  except Exception as e:
   self.db.result(r['id'],'REVISAO',error=str(e),attempt=True);self.log.error('[META] Falha ao preparar %s: %s',r['nome'],e)
  finally:self.changed()
class Scheduler:
 def __init__(self,db,pub):self.db=db;self.pub=pub;self.stop=threading.Event();self.pause=threading.Event();self.thread=None
 def start(self):
  if self.thread and self.thread.is_alive():return
  self.stop.clear();self.thread=threading.Thread(target=self.loop,daemon=True,name='scheduler');self.thread.start()
 def loop(self):
  while not self.stop.wait(2):
   if not self.pause.is_set():
    for r in self.db.all():
     if r['status']=='AGENDADO' and r.get('data_agendada'):
      threading.Thread(target=self.pub.prepare_remote,args=(r,),daemon=True).start()
    for r in self.db.due():threading.Thread(target=self.pub.publish,args=(r,),daemon=True).start()
class App:
 def __init__(self):
  self.cfg=Config();self.db=DB();self.log=logger();self.db.recover();self.queue=Queue(self.cfg,self.db,self.log);self.root=tk.Tk();self.root.title('Publication Manager Automático');self.root.geometry('1240x780');self.root.minsize(980,620);self.pub=Publisher(self.cfg,self.db,self.log,lambda:self.root.after(0,self.refresh));self.oauth=MetaOAuth(self.cfg);self.scan=Scanner(self.cfg,self.db,self.log,lambda:self.root.after(0,self.refresh),lambda n:self.queue.fill());self.sched=Scheduler(self.db,self.pub);self.active=False;self.build();self.refresh();self.root.protocol('WM_DELETE_WINDOW',self.close)
 def build(self):
  s=ttk.Style();s.configure('Title.TLabel',font=('Segoe UI Semibold',22));s.configure('Metric.TLabel',font=('Segoe UI Semibold',17));s.configure('Treeview',rowheight=29);f=ttk.Frame(self.root,padding=22);f.pack(fill='both',expand=True)
  top=ttk.Frame(f);top.pack(fill='x');ttk.Label(top,text='PUBLICATION MANAGER',style='Title.TLabel').pack(side='left');self.mode=ttk.Label(top,font=('Segoe UI Semibold',11));self.mode.pack(side='right');self.state=ttk.Label(top,font=('Segoe UI Semibold',11));self.state.pack(side='right',padx=20)
  info=ttk.LabelFrame(f,text=' STATUS DO SISTEMA ',padding=12);info.pack(fill='x',pady=(18,10));self.folder_label=ttk.Label(info);self.folder_label.grid(row=0,column=0,columnspan=4,sticky='w');self.cutter_state=ttk.Label(info);self.cutter_state.grid(row=1,column=0,sticky='w',pady=5);self.meta_state=ttk.Label(info);self.meta_state.grid(row=1,column=1,sticky='w',padx=35);self.platform_state=ttk.Label(info);self.platform_state.grid(row=1,column=2,sticky='w')
  m=ttk.Frame(f);m.pack(fill='x',pady=8);self.metrics={}
  for k,l in [('total','Encontrados'),('pending','Na fila'),('scheduled','Agendados'),('published','Publicados'),('errors','Revisão/erros')]:b=ttk.Frame(m,padding=(0,0,45,0));b.pack(side='left');self.metrics[k]=ttk.Label(b,text='0',style='Metric.TLabel');self.metrics[k].pack();ttk.Label(b,text=l).pack()
  nxt=ttk.Frame(f,padding=(0,8));nxt.pack(fill='x');ttk.Label(nxt,text='PRÓXIMA PUBLICAÇÃO').pack(anchor='w');self.next=ttk.Label(nxt,text='Nenhuma',font=('Segoe UI Semibold',14));self.next.pack(anchor='w')
  ttk.Label(f,text='FILA DE PUBLICAÇÕES',font=('Segoe UI Semibold',12)).pack(anchor='w',pady=(8,4));self.table=ttk.Treeview(f,columns=('n','v','d','h','p','s'),show='headings')
  for c,t,w in [('n','#',45),('v','Vídeo',430),('d','Data',110),('h','Hora',80),('p','Plataforma',120),('s','Status',120)]:self.table.heading(c,text=t);self.table.column(c,width=w,anchor='w' if c=='v' else 'center')
  self.table.pack(fill='both',expand=True);bar=ttk.Frame(f);bar.pack(fill='x',pady=(14,0))
  for t,cmd in [('INICIAR',self.start),('Parar',self.stop),('Atualizar agora',self.manual_scan),('Agendar fila',self.fill),('Conectar Meta',self.connect_meta),('Configurações',self.settings),('Testar Meta',self.test)]:ttk.Button(bar,text=t,command=cmd).pack(side='left',padx=(0,7))
  self.testvar=tk.BooleanVar(value=self.cfg.data['test_mode']);ttk.Checkbutton(bar,text='Modo teste',variable=self.testvar,command=self.toggle).pack(side='right')
 def run(self):
  if self.cfg.data.get('auto_monitor') and self.cfg.folder.exists():self.start()
  self.root.mainloop()
 def validate_start(self):
  try:self.cfg.refresh_integration()
  except Exception as e:self.log.warning('[INTEGRAÇÃO] %s',e)
  if not self.cfg.folder.exists():raise ValueError('Configure uma pasta de saída válida do Auto Video Cutter.')
 def start(self):
  try:self.validate_start();lost=self.queue.recover_missed();self.scan.scan();self.queue.fill();self.scan.start();self.sched.start();self.active=True;self.state.config(text='🟢 MONITORAMENTO ATIVO');self.refresh()
  except Exception as e:messagebox.showerror('Não foi possível iniciar',str(e))
 def stop(self):self.scan.halt();self.sched.stop.set();self.active=False;self.state.config(text='PARADO')
 def close(self):self.stop();self.root.destroy()
 def manual_scan(self):threading.Thread(target=lambda:(self.scan.scan(),self.queue.fill()),daemon=True).start()
 def toggle(self):
  new=self.testvar.get()
  if not new and not messagebox.askyesno('Ativar publicação real','Você está prestes a ativar publicação real no Facebook/Instagram. Continuar?'):
   self.testvar.set(True);return
  self.cfg.data['test_mode']=new;self.cfg.data['real_publication_confirmed']=not new;self.cfg.save();self.refresh()
 def fill(self):n=self.queue.fill();messagebox.showinfo('Fila',f'{n} vídeo(s) agendado(s).');self.refresh()
 def meta_label(self):
  m=self.cfg.data['meta'];page=m.get('facebook_page_name');ig=m.get('instagram_username');return f"🟢 Meta: {page}"+(f" / @{ig}" if ig else '') if page else '⚪ Meta não conectada'
 def refresh(self):
  self.state.config(text='🟢 MONITORAMENTO ATIVO' if self.active else '⚪ PARADO');self.mode.config(text='🟡 MODO TESTE ATIVO: nenhuma publicação real' if self.cfg.data['test_mode'] else '🔴 PUBLICAÇÃO REAL ATIVA');folder=self.cfg.folder;self.folder_label.config(text=f'Pasta monitorada: {folder if str(folder) else "não configurada"}');self.cutter_state.config(text='🟢 AUTO VIDEO CUTTER CONECTADO' if folder.exists() else '🔴 AUTO VIDEO CUTTER DESCONECTADO');self.meta_state.config(text=self.meta_label());p=self.cfg.data['platforms'];self.platform_state.config(text=f"Facebook: {'🟢' if p['facebook_reels'] else '⚪'}  Instagram: {'🟢' if p['instagram_reels'] else '⚪'}")
  for k,v in self.db.stats().items():self.metrics[k].config(text=str(v))
  self.table.delete(*self.table.get_children());future=[];plat=('FB + IG' if all(p.values()) else 'FB' if p['facebook_reels'] else 'IG' if p['instagram_reels'] else 'Nenhuma')
  for i,r in enumerate(self.db.all(),1):
   d=h=''
   if r['data_agendada']:
    x=datetime.fromisoformat(r['data_agendada']).astimezone(self.cfg.tz);d=x.strftime('%d/%m/%Y');h=x.strftime('%H:%M')
    if r['status']=='AGENDADO':future.append((x,r))
   self.table.insert('','end',values=(i,r['nome'],d,h,plat,r['status']))
  self.next.config(text=(lambda x:f"{x[1]['nome']} | {x[0]:%d/%m/%Y às %H:%M}")(min(future)) if future else ('Aguardando novos vídeos...' if self.active else 'Nenhuma publicação agendada'))
 def connect_meta(self):
  def work():
   try:r=self.oauth.connect();self.root.after(0,lambda:self.connected(r))
   except Exception as e:self.root.after(0,lambda x=str(e):messagebox.showerror('Falha ao conectar Meta',x))
  threading.Thread(target=work,daemon=True).start()
 def connected(self,r):self.refresh();messagebox.showinfo('Meta conectada',f"Página {r['page']} conectada"+(f" e Instagram @{r['instagram']}" if r.get('instagram') else ''))
 def settings(self):
  w=tk.Toplevel(self.root);w.title('Configurações');w.geometry('820x680');w.transient(self.root);f=ttk.Frame(w,padding=22);f.pack(fill='both',expand=True);f.columnconfigure(1,weight=1);a=self.cfg.data['auto_video_cutter'];vars={k:tk.StringVar(value=v) for k,v in {'project':a.get('project_dir',''),'input':a.get('input_dir',''),'output':self.cfg.data.get('output_dir',''),'tz':self.cfg.data['timezone'],'times':', '.join(self.cfg.data['publication_times']),'custom':self.cfg.data['first_publication'].get('custom_datetime','')}.items()}
  row=0;ttk.Label(f,text='AUTO VIDEO CUTTER',font=('Segoe UI Semibold',13)).grid(row=row,column=0,columnspan=3,sticky='w',pady=(0,8));row+=1
  for label,key in [('Pasta do projeto', 'project'),('Pasta de entrada','input'),('Pasta de saída / monitorada','output')]:ttk.Label(f,text=label).grid(row=row,column=0,sticky='w',pady=6);ttk.Entry(f,textvariable=vars[key]).grid(row=row,column=1,sticky='ew',padx=10);row+=1
  def apply_info(info):
   vars['project'].set(info['project_dir']);vars['input'].set(info['input_dir']);vars['output'].set(info['output_dir'])
  def detect():
   try:apply_info(FolderResolver(BASE).detect(vars['project'].get()))
   except Exception as e:messagebox.showerror('Detecção',str(e),parent=w)
  def choose():
   p=filedialog.askdirectory(parent=w,title='Escolha a pasta do projeto Auto Video Cutter')
   if p:
    try:apply_info(FolderResolver(BASE).inspect(p))
    except Exception as e:messagebox.showerror('Pasta inválida',str(e),parent=w)
  ttk.Button(f,text='DETECTAR AUTOMATICAMENTE',command=detect).grid(row=row,column=1,sticky='w',padx=10,pady=8);ttk.Button(f,text='ESCOLHER PASTA',command=choose).grid(row=row,column=2,sticky='w');row+=1;ttk.Separator(f).grid(row=row,column=0,columnspan=3,sticky='ew',pady=12);row+=1
  for label,key in [('Timezone','tz'),('Horários (vírgula)','times')]:ttk.Label(f,text=label).grid(row=row,column=0,sticky='w',pady=6);ttk.Entry(f,textvariable=vars[key]).grid(row=row,column=1,sticky='ew',padx=10);row+=1
  ttk.Label(f,text='Primeira publicação').grid(row=row,column=0,sticky='nw',pady=6);first=tk.StringVar(value=self.cfg.data['first_publication']['mode']);box=ttk.Frame(f);box.grid(row=row,column=1,sticky='w',padx=10)
  for text,val in [('Próximo horário disponível','next'),('Amanhã às 12:45','tomorrow'),('Escolher data e horário','custom')]:ttk.Radiobutton(box,text=text,value=val,variable=first).pack(anchor='w')
  ttk.Entry(box,textvariable=vars['custom'],width=25).pack(anchor='w',pady=3);row+=1
  missed=tk.StringVar(value=self.cfg.data['missed_policy']);ttk.Label(f,text='Horário perdido').grid(row=row,column=0,sticky='w');ttk.Combobox(f,textvariable=missed,values=['reschedule','skip'],state='readonly').grid(row=row,column=1,sticky='w',padx=10);row+=1
  auto=tk.BooleanVar(value=self.cfg.data.get('auto_monitor',True));startup=tk.BooleanVar(value=self.cfg.data.get('start_with_windows',False));ttk.Checkbutton(f,text='Monitoramento automático',variable=auto).grid(row=row,column=1,sticky='w',padx=10);row+=1;ttk.Checkbutton(f,text='Iniciar automaticamente com o Windows',variable=startup).grid(row=row,column=1,sticky='w',padx=10);row+=1
  def save():
   try:
    info=FolderResolver(BASE).inspect(vars['project'].get()) if vars['project'].get() else {'project_dir':'','input_dir':'','output_dir':vars['output'].get(),'config_path':''};info['output_dir']=vars['output'].get();self.cfg.data['auto_video_cutter'].update(info);self.cfg.data['output_dir']=vars['output'].get();self.cfg.data['timezone']=vars['tz'].get();self.cfg.data['publication_times']=[x.strip() for x in vars['times'].get().split(',') if x.strip()];self.cfg.data['first_publication']={'mode':first.get(),'time':self.cfg.data['publication_times'][0],'custom_datetime':vars['custom'].get()};self.cfg.data['missed_policy']=missed.get();self.cfg.data['auto_monitor']=auto.get();self.cfg.data['start_with_windows']=startup.get();self.cfg.save();configure_startup(startup.get());self.refresh();w.destroy()
   except Exception as e:messagebox.showerror('Erro',str(e),parent=w)
  ttk.Button(f,text='SALVAR',command=save).grid(row=row,column=1,sticky='e',pady=18)
 def test(self):
  def work():
   try:r=self.pub.api.test();self.root.after(0,lambda:messagebox.showinfo('Conexão OK',str(r)))
   except Exception as e:self.root.after(0,lambda x=str(e):messagebox.showerror('Falha',x))
  threading.Thread(target=work,daemon=True).start()
def configure_startup(enable):
 if os.name!='nt':return
 startup=Path(os.environ.get('APPDATA',''))/'Microsoft/Windows/Start Menu/Programs/Startup';link=startup/'PublicationManagerAuto.cmd'
 if enable:
  link.write_text(f'@echo off\nstart "" /min "{sys.executable}" "{BASE/"main.py"}"\n',encoding='utf-8')
 elif link.exists():link.unlink()
