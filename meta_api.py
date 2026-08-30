import hashlib
import hmac
import os
import time

import requests


class MetaError(RuntimeError):
 def __init__(self,msg,transient=False,uncertain=False):super().__init__(msg);self.transient=transient;self.uncertain=uncertain


class MetaAPI:
 def __init__(self,cfg,checkpoint,store=None):
  self.cfg=cfg;self.v=cfg.data['meta']['graph_version'];self.s=requests.Session();self.checkpoint=checkpoint
  if store is None:
   from meta_auth import TokenStore
   store=TokenStore()
  self.store=store
 def user_token(self):return self.store.user_token()
 def page_token(self):return self.store.page_token(self.cfg.data['meta']['facebook_page_id'])
 def proof(self,token):
  secret=os.getenv('META_APP_SECRET','').strip()
  return hmac.new(secret.encode(),token.encode(),hashlib.sha256).hexdigest() if secret and token else ''
 def req(self,method,url,final=False,**kw):
  try:r=self.s.request(method,url,timeout=(20,180),**kw)
  except requests.RequestException as e:raise MetaError(str(e),transient=not final,uncertain=final)
  try:j=r.json()
  except ValueError:j={'raw':r.text[:500]}
  if not r.ok or 'error' in j:
   e=j.get('error',{});raise MetaError(e.get('message') or f'HTTP {r.status_code}: {j}',bool(e.get('is_transient')) or r.status_code>=500,final and (bool(e.get('is_transient')) or r.status_code>=500))
  return j
 def require(self,platform):
  m=self.cfg.data['meta'];token=self.page_token() if platform=='facebook' else self.user_token()
  if not token:raise MetaError('Meta não conectada. Use “Conectar Meta”.')
  expires=m.get('token_expires_at',0)
  if platform=='instagram' and expires and time.time()>=expires:raise MetaError('A autorização da Meta expirou. Conecte novamente.')
  if platform=='facebook' and not m.get('facebook_page_id'):raise MetaError('Nenhuma Página do Facebook selecionada.')
  if platform=='instagram' and not m.get('instagram_user_id'):raise MetaError('A Página selecionada não possui uma conta Instagram profissional vinculada.')
  return token
 def params(self,token,**extra):
  out={'access_token':token,**extra};proof=self.proof(token)
  if proof:out['appsecret_proof']=proof
  return out
 def test(self):
  m=self.cfg.data['meta'];out={}
  if m.get('facebook_page_id'):
   token=self.require('facebook');out['facebook']=self.req('GET',f"https://graph.facebook.com/{self.v}/{m['facebook_page_id']}",params=self.params(token,fields='id,name'))
  if m.get('instagram_user_id'):
   token=self.require('instagram');out['instagram']=self.req('GET',f"https://graph.facebook.com/{self.v}/{m['instagram_user_id']}",params=self.params(token,fields='id,username'))
  if not out:raise MetaError('Conecte a Meta e selecione uma Página disponível.')
  return out
 def instagram(self,row,caption=None):
  token=self.require('instagram');ig=self.cfg.data['meta']['instagram_user_id'];j=self.req('POST',f'https://graph.facebook.com/{self.v}/{ig}/media',data=self.params(token,media_type='REELS',upload_type='resumable',caption=caption if caption is not None else row['legenda'],share_to_feed=str(self.cfg.data['meta']['share_instagram_reel_to_feed']).lower()));cid=j['id'];self.checkpoint(row['id'],{'instagram_container_id':cid});url=j.get('uri') or f'https://rupload.facebook.com/ig-api-upload/{self.v}/{cid}';size=os.path.getsize(row['arquivo_mp4'])
  with open(row['arquivo_mp4'],'rb') as f:self.req('POST',url,headers={'Authorization':f'OAuth {token}','offset':'0','file_size':str(size)},data=f)
  end=time.monotonic()+900
  while time.monotonic()<end:
   st=self.req('GET',f'https://graph.facebook.com/{self.v}/{cid}',params=self.params(token,fields='status_code,status'))
   if st.get('status_code')=='FINISHED':break
   if st.get('status_code') in ('ERROR','EXPIRED'):raise MetaError(f'Container falhou: {st}')
   time.sleep(5)
  else:raise MetaError('Timeout processando no Instagram.',True)
  p=self.req('POST',f'https://graph.facebook.com/{self.v}/{ig}/media_publish',final=True,data=self.params(token,creation_id=cid));return {'instagram_container_id':cid,'instagram_media_id':p['id']}
 def facebook(self,row,scheduled_at=None,description=None):
  token=self.require('facebook');page=self.cfg.data['meta']['facebook_page_id'];j=self.req('POST',f'https://graph.facebook.com/{self.v}/{page}/video_reels',data=self.params(token,upload_phase='start'));vid=j['video_id'];self.checkpoint(row['id'],{'facebook_video_id':vid});size=os.path.getsize(row['arquivo_mp4'])
  with open(row['arquivo_mp4'],'rb') as f:self.req('POST',j['upload_url'],headers={'Authorization':f'OAuth {token}','offset':'0','file_size':str(size)},data=f)
  finish={'upload_phase':'finish','video_id':vid,'description':description if description is not None else row['legenda']}
  if scheduled_at:
   finish.update(video_state='SCHEDULED',scheduled_publish_time=str(int(scheduled_at.timestamp())))
  else: finish['video_state']='PUBLISHED'
  self.req('POST',f'https://graph.facebook.com/{self.v}/{page}/video_reels',final=True,data=self.params(token,**finish));return {'facebook_video_id':vid,'facebook_scheduled':bool(scheduled_at)}
