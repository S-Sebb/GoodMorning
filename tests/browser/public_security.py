"""Opt-in root/SSH public-domain trial using three synthetic encrypted accounts.

No model calls, real profile reads, credentials in output, or permanent user edits.
Synthetic evidence stays encrypted; accounts are disabled and services stopped.
"""
import argparse
from datetime import datetime,timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPCookieProcessor

sys.path.insert(0,'/opt/goodmorning/current/src')
from goodmorning.security.briefing_accounts import Accounts,encrypted_mount,REMEMBER_SECONDS
from goodmorning.briefings.briefing_document import encode
from goodmorning.security.briefing_vault import initialize,provision_user
from goodmorning.runtime_files import atomic_text


def command(args):
    subprocess.run(args,check=True,capture_output=True,timeout=30)


class Client:
    def __init__(self,origin):
        self.origin=origin;self.jar=CookieJar();self.opener=build_opener(HTTPCookieProcessor(self.jar));self.csrf=None

    def call(self,path='/',body=None,headers=None):
        time.sleep(.55)  # Respect the production rate limit; not a readiness poll.
        values={'Accept':'application/json'}
        if body is not None:values.update({'Content-Type':'application/json','Origin':self.origin,'X-Briefing-CSRF':self.csrf or ''})
        values.update(headers or {})
        request=Request(self.origin+path,data=json.dumps(body).encode() if body is not None else None,headers=values)
        try:response=self.opener.open(request,timeout=10)
        except HTTPError as error:response=error
        with response:return response.status,dict(response.headers),response.read()

    def form(self,path):
        status,headers,data=self.call(path)
        assert status==200
        self.csrf=re.search(rb'data-csrf="([a-f0-9]+)"',data)[1].decode()
        return data


def run(root,origin):
    assert os.geteuid()==0 and origin=='https://gm.love765.me'
    mount=encrypted_mount(root/'live/accounts');store=Accounts(mount)
    registry_path=mount/'backends.json';registry=json.loads(registry_path.read_text())
    created=[];provisioned=[];chats={};report={'kind':'synthetic_public_security','modelCalls':0,'accounts':3,'checks':[]}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    try:
        for index in range(3):
            name='trial-'+secrets.token_hex(5)+'-'+str(index)
            temporary=('a'+f'{secrets.randbelow(100000):05d}') if index==0 else secrets.token_urlsafe(20)+'a1'
            permanent='a1'+secrets.token_urlsafe(24)[:30]
            identifier=store.create(name,temporary);provisioned.append((name,identifier))
            initialize(root,identifier)
            linux=provision_user(root,identifier);user=pwd.getpwnam(linux)
            volume=root/'live'/identifier;runtime=volume/'secretary'
            canary='PRIVATE-SYNTHETIC-'+secrets.token_hex(16)
            (runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            (runtime/'daily').mkdir(mode=0o700)
            from goodmorning.briefings.briefing_day import briefing_day
            day=briefing_day('Europe/London')
            document={'v':1,'greeting':'Synthetic security fixture','opening':'No AI generation occurred.',
                      'sections':[['must-do',[['tasks',[['open',canary,'Synthetic record, not a real user task.']]]]]]}
            (runtime/'daily'/(day+'.gm.json')).write_text(encode(document))
            chat=secrets.token_hex(16);chats[identifier]=chat
            (runtime/'browser-chats').mkdir(mode=0o700)
            (runtime/'browser-chats/chats.json').write_text(json.dumps({chat:{'id':chat,'mode':'secretary','title':canary,'state':'uncertain','turns':[]}}))
            key=secrets.token_urlsafe(32);(volume/'gateway.key').write_text(key)
            for p in volume.rglob('*'):
                if not p.is_symlink():os.chown(p,user.pw_uid,user.pw_gid);p.chmod(0o700 if p.is_dir() else 0o600)
            port=18810+index;unit='goodmorning-security-'+identifier
            registry[identifier]={'port':port,'key':key}
            atomic_text(registry_path,json.dumps(registry))
            command(['systemd-run','--unit',unit,'--property=User='+linux,'--property=Group='+linux,
                     '--property=MemorySwapMax=0','--property=LimitCORE=0','--property=StandardOutput=null','--property=StandardError=null',
                     '--setenv=PYTHONDONTWRITEBYTECODE=1',sys.executable,'/opt/goodmorning/current/scripts/goodmorning.py','serve',
                     '--secretary-dir',str(runtime),'--port',str(port),'--gateway-key-file',str(volume/'gateway.key'),
                     '--public-origin',origin,'--public-origin','https://gn.love765.me','--public-origin','https://sec.love765.me'])
            client=Client(origin);created.append((name,identifier,linux,unit,client,canary,permanent))
            login=client.form('/login')
            assert b'data-password-target="password-password"' in login and b'name="remember"' in login
            status,headers,data=client.call('/api/auth/login',{'username':name,'password':temporary,'remember':True})
            assert status==200 and json.loads(data)['next']=='/password'
            assert 'Max-Age='+str(REMEMBER_SECONDS) in headers['Set-Cookie'] and 'Domain=' not in headers['Set-Cookie']
            client.form('/password')
            if index==0:
                for rejected in ('abc12','abcdef','123456','a1'+'x'*31):
                    status,_,data=client.call('/api/auth/password',{'current':temporary,'replacement':rejected})
                    assert status==400 and '6–32 characters' in json.loads(data)['error']
            old_token=next(c.value for c in client.jar if c.name=='__Host-GoodMorning')
            status,headers,_=client.call('/api/auth/password',{'current':temporary,'replacement':permanent})
            assert status==200
            assert 'Max-Age='+str(REMEMBER_SECONDS) in headers['Set-Cookie']
            from goodmorning.security.briefing_accounts import Denied
            try:store.session(old_token,'gm.love765.me');raise AssertionError('Old token remained valid')
            except Denied:pass
            status,headers,data=client.call('/')
            assert status==200 and canary.encode() in data and headers['Cache-Control']=='no-store'
            client.csrf=re.search(rb'id="sign-out" data-csrf="([a-f0-9]+)"',data)[1].decode()
            token=next(c.value for c in client.jar if c.name=='__Host-GoodMorning')
            assert store.session(token,'gm.love765.me')['remembered']==1
            status,_,data=client.call('/chat')
            assert status==200 and b'role="radiogroup"' in data and b'&quot;defaultMode&quot;: &quot;secretary&quot;' in data
            if index==0:
                profile=runtime/'profile.md';saved_profile=profile.read_text()
                saved_edition=(runtime/'daily'/(day+'.gm.json')).read_bytes()
                profile.write_text('timezone: Europe/London\n')
                status,_,page=client.call('/gn.html')
                assert status==200 and b'Initialize my secretary' in page and b'id="generate"' not in page
                assert b'href="/chat?mode=initialize"' in page
                assert client.call('/api/generate',{'date':day,'kind':'gn'})[0]==400
                assert (runtime/'daily'/(day+'.gm.json')).read_bytes()==saved_edition
                assert canary.encode() in client.call('/gm.html')[2]
                profile.write_text(saved_profile)
                report['checks'].append('incomplete setup: Initialize link replaces generation; direct dispatch refused; saved edition preserved and readable')
            secretary=Client('https://sec.love765.me')
            secretary.form('/login')
            status,headers,_=secretary.call('/api/auth/login',{'username':name,'password':permanent,'remember':True})
            assert status==200 and 'Domain=' not in headers['Set-Cookie']
            status,_,page=secretary.call('/')
            assert status==200 and b'role="radiogroup"' in page and b'id="chat-config"' in page
            secretary.csrf=re.search(rb'id="sign-out" data-csrf="([a-f0-9]+)"',page)[1].decode()
            assert secretary.call('/api/chats')[0]==200
            assert secretary.call('/api/chats',{},headers={'Origin':origin})[0]==403
            assert secretary.call('/api/chats',headers={'Cookie':'__Host-GoodMorning='+token})[0]==401
            report['checks'].append('account-'+str(index)+': secretary-host root/chat mapping, independent remembered login, sibling token and origin rejected')
            status,_,data=client.call('/api/chats')
            assert status==200 and canary.encode() in data
            assert canary.encode() not in b''.join(p.read_bytes() for p in (root/'cipher'/identifier).rglob('*') if p.is_file())
            report['checks'].append('account-'+str(index)+': HTTPS remembered login, preference survives forced password change, token revocation, private briefing/chat rendering, ciphertext canary absent')
            originals={path:path.read_bytes() for path in (runtime/'profile.md',runtime/'daily'/(day+'.gm.json'))}
            selected='zh-CN' if index==0 else 'en'
            status,headers,data=client.call('/api/language',{'language':selected})
            assert status==200 and json.loads(data)['language']==selected
            assert 'GoodMorningLanguage='+selected in headers['Set-Cookie'] and 'Domain=love765.me' in headers['Set-Cookie']
            assert store.website_language(identifier)==selected
            assert json.loads(secretary.call('/api/language')[2])['language']==selected
            night=Client('https://gn.love765.me');night.form('/login')
            assert night.call('/api/auth/login',{'username':name,'password':permanent})[0]==200
            assert json.loads(night.call('/api/language')[2])['language']==selected
            if selected=='zh-CN':
                assert '网站语言'.encode() in secretary.call('/chat')[2]
                page=client.call('/')[2]
                assert '查看已保存的数据'.encode() in page and b'Synthetic security fixture' in page
            assert client.call('/api/language',{'language':'zh-TW'})[0]==400
            assert client.call('/api/language',{'language':'en'},headers={'Origin':'https://evil.example'})[0]==403
            assert client.call('/api/language',{'language':'en'},headers={'X-Briefing-CSRF':'invalid'})[0]==403
            assert store.website_language(identifier)==selected
            assert all(path.read_bytes()==value for path,value in originals.items())
            report['checks'].append('account-'+str(index)+': language shared by three authenticated HTTPS hosts/devices, host-only auth, original records unchanged, invalid language/origin/CSRF denied')
        report['checks'].append('password policy: actual HTTPS accepts 6 and 32 characters, rejects 5/33 or missing letter/digit')
        assert [store.website_language(identifier) for _,identifier,*_ in created]==['zh-CN','en','en']
        report['accountLanguageIsolation']=True
        for index,(name,identifier,linux,unit,client,canary,permanent) in enumerate(created):
            status,_,data=client.call('/')
            assert all(other.encode() not in data for _,_,_,_,_,other,_ in created if other!=canary)
            assert client.call('/api/jobs/'+('a'*32))[0]==404
            status,_,data=client.call('/api/chats')
            assert status==200 and all(other.encode() not in data for _,_,_,_,_,other,_ in created if other!=canary)
            assert client.call('/api/chats/'+chats[created[(index+1)%3][1]])[0]==404
            assert client.call('/api/chats',{'id':secrets.token_hex(16),'mode':'initialize','text':''},headers={'Origin':'https://evil.example'})[0]==403
            assert client.call('/api/generate',{'date':day,'kind':'gm'},headers={'Origin':'https://evil.example'})[0]==403
            assert client.call('/api/auth/rename',{'name':'other'})[0]==403
            other=root/'live'/created[(index+1)%3][1]/'secretary/profile.md'
            result=subprocess.run(['runuser','-u',linux,'--','cat',str(other)],capture_output=True)
            assert result.returncode!=0
            report['checks'].append('account-'+str(index)+': cross-account web/chat/job/file denial, CSRF rejection, no web rename')
        name,identifier,linux,unit,client,canary,permanent=created[0]
        command(['systemctl','stop',unit])
        command(['fusermount3','-u',str(root/'live'/identifier)])
        try:encrypted_mount(root/'live'/identifier);raise AssertionError('Unmounted volume accepted')
        except ValueError:pass
        result=subprocess.run(['runuser','-u',linux,'--','touch',str(root/'live'/identifier/'plaintext-fallback')],capture_output=True)
        assert result.returncode!=0
        from goodmorning.security.briefing_vault import mount as mount_volume
        # Restore only this stopped synthetic account into independent private paths.
        restore=root/'trials'/(stamp+'-backup-restore')
        restore.mkdir(parents=True,mode=0o700)
        for folder in ('cipher','keys','live'):(restore/folder).mkdir(mode=0o700)
        shutil.copytree(root/'cipher'/identifier,restore/'cipher'/identifier)
        shutil.copy2(root/'keys'/(identifier+'.key'),restore/'keys'/(identifier+'.key'))
        (restore/'live'/identifier).mkdir(mode=0o700)
        restored=mount_volume(restore,identifier)
        try:
            assert canary in (restored/'secretary/daily'/(day+'.gm.json')).read_text()
        finally:
            command(['fusermount3','-u',str(restored)])
        report['checks'].append('independent synthetic ciphertext backup and saved-key restoration preserved the briefing; restored volume unmounted')
        report['encryptedBackupAndKeyRestore']=True
        mount_volume(root,identifier)
        assert canary in (root/'live'/identifier/'secretary/daily'/(day+'.gm.json')).read_text()
        report['checks'].append('encrypted unmount/remount preserved data; missing-mount and plaintext-fallback denied')
        report['passed']=True
    finally:
        unmounted=0
        for name,identifier in provisioned:
            subprocess.run(['systemctl','stop','goodmorning-security-'+identifier],capture_output=True)
            store.administer(name,enabled=False)
            registry.pop(identifier,None)
            live=root/'live'/identifier
            if os.path.ismount(live):
                subprocess.run(['fusermount3','-u',str(live)],capture_output=True)
            unmounted+=not os.path.ismount(live)
        atomic_text(registry_path,json.dumps(registry))
        report['syntheticAccountsDisabled']=len(provisioned)
        report['syntheticVolumesUnmounted']=unmounted
        if unmounted!=len(provisioned):report['passed']=False
        atomic_text(mount/('security-test-'+stamp+'.json'),json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault-root',type=Path,required=True)
    parser.add_argument('--origin',required=True)
    args=parser.parse_args();run(args.vault_root,args.origin)
