"""Per-account runtime launcher; all private paths stay inside the encrypted volume."""
import argparse
import base64
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from urllib.request import Request, build_opener

from .briefing_accounts import encrypted_mount
from goodmorning.web.briefing_server import BrowserApp, Chamber, NoRedirect, serve_live
from goodmorning.paths import ROOT
from goodmorning.web.bridge_json import read_json


class LocalBridge(Chamber):
    """This account's engine, behind OpenCode's own server password. Never blindly replays a request."""
    def __init__(self,url,directory,password):
        super().__init__(url,directory)
        self.authorization='Basic '+base64.b64encode(('opencode:'+password).encode()).decode()

    def request(self,path,body=None,method=None):
        from urllib.parse import quote
        headers={'Authorization':self.authorization,'x-opencode-directory':quote(self.directory,safe='')}
        if body is not None:headers['Content-Type']='application/json'
        request=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        with build_opener(NoRedirect).open(request,timeout=20) as response:
            return read_json(response, attachment_data=path.split('?')[0].endswith(('/prompt', '/message')),
                             message_data=path.split('?')[0].endswith('/message'))


PROVIDER_KEYS=('MAL_CLIENT_ID',)
# An engine with no connections and no running session exits after this long;
# its systemd socket keeps the port and starts it again on the next connection.
IDLE_SECONDS=600


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        return probe.getsockname()[1]


class Supervisor:
    """Runs `opencode serve` on a private port and relays this account's engine port to it.

    The relay sees every connection, so it knows when the engine is idle; a parked
    question keeps its session running, so the engine stays up while one waits."""
    def __init__(self,listener,command,env,password,directory,idle=IDLE_SECONDS):
        self.listener,self.idle=listener,idle
        self.port=free_port()
        self.process=subprocess.Popen([*command,'serve','--hostname','127.0.0.1','--port',str(self.port)],
                                      env={**env,'OPENCODE_SERVER_PASSWORD':password},
                                      stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL)
        self.bridge=LocalBridge('http://127.0.0.1:'+str(self.port),directory,password)
        self.lock,self.open,self.last=threading.Lock(),0,time.monotonic()
        self.stopping=False

    def touch(self,change=0):
        with self.lock:
            self.open+=change
            self.last=time.monotonic()

    def upstream(self):
        deadline=time.monotonic()+30
        while True:
            try:
                return socket.create_connection(('127.0.0.1',self.port),timeout=5)
            except OSError:
                if self.process.poll() is not None or time.monotonic()>deadline:
                    raise
                time.sleep(0.05)

    def relay(self,client):
        self.touch(1)
        try:
            with client,self.upstream() as server:
                server.settimeout(None)
                def pump(source,target):
                    try:
                        while data:=source.recv(65536):
                            target.sendall(data)
                            self.touch()
                    except OSError:
                        pass
                    finally:
                        try:target.shutdown(socket.SHUT_WR)
                        except OSError:pass
                back=threading.Thread(target=pump,args=(server,client),daemon=True)
                back.start()
                pump(client,server)
                back.join()
        except OSError:
            pass
        finally:
            self.touch(-1)

    def accept(self):
        self.listener.settimeout(1)
        while not self.stopping:
            try:
                client,_=self.listener.accept()
            except TimeoutError:
                continue
            client.settimeout(None)
            threading.Thread(target=self.relay,args=(client,),daemon=True).start()

    def quiet(self):
        with self.lock:
            if self.open or time.monotonic()-self.last<self.idle:
                return False
        try:
            return not self.bridge.request('/api/session/active')['data']
        except Exception:
            return False  # An unanswered check never stops running work.

    def run(self,check=30):
        threading.Thread(target=self.accept,daemon=True).start()
        while self.process.poll() is None:
            if self.quiet():
                # Stop accepting first: a connection arriving now waits in the socket's
                # queue, and systemd starts the engine again for it.
                self.stopping=True
                time.sleep(1.5)
                if self.quiet():
                    break
                self.stopping=False
                threading.Thread(target=self.accept,daemon=True).start()
            time.sleep(check)
        else:
            return 1  # The engine exited on its own; systemd restarts it.
        self.stop()
        return 0

    def stop(self,*_):
        self.process.terminate()
        try:
            self.process.wait(20)
        except subprocess.TimeoutExpired:
            self.process.kill()


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
    # systemd passes the account's engine socket as file descriptor 3.
    activated=os.environ.get('LISTEN_PID')==str(os.getpid()) and os.environ.get('LISTEN_FDS')=='1'
    source=ROOT
    home=volume/'home'
    # Only named, server-wide provider identifiers pass the cleared environment.
    providers={key:os.environ[key] for key in PROVIDER_KEYS if os.environ.get(key)}
    env={'HOME':str(home),'USER':os.environ['USER'],'LOGNAME':os.environ['USER'],
         'PATH':'/opt/goodmorning/engine/bin:/usr/local/bin:/usr/bin:/bin',
         'XDG_CONFIG_HOME':str(home/'.config'),'XDG_DATA_HOME':str(home/'.local/share'),
         'XDG_CACHE_HOME':str(home/'.cache'),'XDG_STATE_HOME':str(home/'.local/state'),
         'XDG_RUNTIME_DIR':str(volume/'run'),'TMPDIR':str(volume/'tmp'),
         'SECRETARY_DIR':str(volume/'secretary'),'GM_CACHE_DIR':str(volume/'cache'),
         'PYTHONDONTWRITEBYTECODE':'1',
         'OPENCODE_CONFIG':str(source/'integrations/opencode/opencode.json'),**providers}
    os.environ.clear();os.environ.update(env)
    os.chdir(source)
    if args.action=='engine':
        if activated:
            listener=socket.socket(fileno=3)
        else:
            listener=socket.create_server(('127.0.0.1',config['chamberPort']))
        supervisor=Supervisor(listener,['/opt/goodmorning/engine/bin/opencode'],env,config['uiPassword'],str(source))
        def finish(*_):
            supervisor.stop()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM,finish)
        raise SystemExit(supervisor.run())
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
