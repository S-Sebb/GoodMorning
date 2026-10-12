"""Per-account runtime launcher; all private paths stay inside the encrypted volume."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .briefing_accounts import encrypted_mount
from goodmorning.web.briefing_server import BrowserApp, Chamber, NoRedirect, serve_live
from goodmorning.paths import ROOT
from goodmorning.web.bridge_json import read_json


class LocalBridge(Chamber):
    """Renew only authentication, never blindly replay an uncertain model dispatch."""
    def __init__(self,url,directory,password):
        super().__init__(url,directory)
        self.password,self.token,self.expires=password,None,0
        self.auth_lock=threading.Lock()

    def authenticate(self,force=False):
        with self.auth_lock:
            if self.token and time.time()<self.expires-60 and not force:
                return self.token
            request=Request(self.url+'/auth/session',headers={'Content-Type':'application/json'},
                            data=json.dumps({'password':self.password,'issueClientToken':True,'trustDevice':False,
                                             'clientLabel':'GoodMorning private account bridge'}).encode())
            with build_opener(NoRedirect).open(request,timeout=15) as response:
                result=json.loads(response.read(100_001))
            self.token=result['clientToken']
            expires=result.get('client',{}).get('expiresAt')
            self.expires=datetime.fromisoformat(expires.replace('Z','+00:00')).timestamp() if expires else time.time()+600
            return self.token

    def request(self,path,body=None):
        from urllib.parse import quote
        for attempt in range(2):
            headers={'Authorization':'Bearer '+self.authenticate(force=attempt==1),
                     'x-opencode-directory':quote(self.directory,safe='')}
            if body is not None:headers['Content-Type']='application/json'
            request=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            try:
                with build_opener(NoRedirect).open(request,timeout=20) as response:
                    return read_json(response, attachment_data=path.split('?')[0].endswith(('/prompt', '/message')))
            except HTTPError as error:
                if error.code!=401 or attempt:raise
                # An explicit authentication rejection guarantees no requested mutation ran.
        raise ValueError('Authentication was not confirmed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--volume',type=Path,required=True)
    parser.add_argument('action',choices=('engine','viewer'))
    args=parser.parse_args()
    volume=encrypted_mount(args.volume)
    if os.geteuid()==0 or volume.stat().st_uid!=os.geteuid():
        raise ValueError('Run as this volume’s dedicated non-root Linux account')
    os.umask(0o077)
    config=json.loads((volume/'engine.json').read_text())
    source=ROOT
    home=volume/'home'
    env={'HOME':str(home),'USER':os.environ['USER'],'LOGNAME':os.environ['USER'],
         'PATH':'/opt/goodmorning/engine/bin:/usr/local/bin:/usr/bin:/bin',
         'XDG_CONFIG_HOME':str(home/'.config'),'XDG_DATA_HOME':str(home/'.local/share'),
         'XDG_CACHE_HOME':str(home/'.cache'),'XDG_STATE_HOME':str(home/'.local/state'),
         'XDG_RUNTIME_DIR':str(volume/'run'),'TMPDIR':str(volume/'tmp'),
         'SECRETARY_DIR':str(volume/'secretary'),'GM_CACHE_DIR':str(volume/'cache'),
         'PYTHONDONTWRITEBYTECODE':'1','OPENCODE_BINARY':'/opt/goodmorning/engine/bin/opencode'}
    os.environ.clear();os.environ.update(env)
    os.chdir(source)
    if args.action=='engine':
        env.update(OPENCHAMBER_UI_PASSWORD=config['uiPassword'],OPENCHAMBER_DATA_DIR=str(home/'.config/openchamber'))
        os.execve('/opt/goodmorning/engine/bin/node',['node','/opt/goodmorning/engine/node_modules/@openchamber/web/bin/cli.js',
            'serve','--foreground','--api-only','--host','127.0.0.1','--port',str(config['chamberPort'])],env)
    else:
        # One process owns this account's job registry; never start a duplicate viewer.
        import fcntl
        lock=(volume/'run/viewer.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        bridge=LocalBridge('http://127.0.0.1:'+str(config['chamberPort']),source,config['uiPassword'])
        app=BrowserApp(volume/'secretary',bridge,preflight=True)
        serve_live(app,config['viewerPort'],gateway_key=config['gatewayKey'],
                   public_origins=('https://gm.love765.me',))


if __name__=='__main__':main()
