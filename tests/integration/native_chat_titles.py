"""Real native auto-title flow against a loopback-only synthetic model provider.

Run explicitly with --binary; never loads the user's engine home or credentials.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            systems = ' '.join(str(item.get('content', '')) for item in body['messages'] if item['role']=='system')
            title = 'title' in systems.lower() and 'generator' in systems.lower()
            calls.append('title' if title else 'reply')
            text = 'Review project priorities' if title else 'Synthetic reply only.'
            result = {'id':'synthetic','object':'chat.completion','model':'synthetic',
                      'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}],
                      'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
            if body.get('stream'):
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                chunk = {**result, 'object':'chat.completion.chunk',
                         'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]}
                end = {**chunk,'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\ndata: '+json.dumps(end)+'\n\ndata: [DONE]\n\n').encode())
            else:
                raw=json.dumps(result).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

    provider=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-native-titles-') as directory:
            root=Path(directory); home=root/'home'; home.mkdir()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            config={'model':'synthetic/synthetic','snapshots':False,
                    'agents':{'title':{'model':'synthetic/synthetic'}},
                    'providers':{'synthetic':{'env':['GM_SYNTHETIC_KEY'],
                        'package':'@opencode/ai/providers/openai-compatible',
                        'settings':{'baseURL':f'http://127.0.0.1:{provider.server_port}/v1'},
                        'models':{'synthetic':{'limit':{'context':32000,'output':1024}}}}}}
            (root/'opencode.json').write_text(json.dumps(config))
            env={'HOME':str(home),'PATH':os.environ['PATH'],'GM_SYNTHETIC_KEY':'synthetic-not-a-secret',
                 'XDG_CONFIG_HOME':str(home/'.config'),'XDG_DATA_HOME':str(home/'.local/share'),
                 'XDG_CACHE_HOME':str(home/'.cache'),'XDG_STATE_HOME':str(home/'.local/state'),
                 'TMPDIR':str(root),'OPENCODE_PASSWORD':'synthetic-engine-only'}
            with (root/'engine.log').open('w+') as log:
                process=subprocess.Popen([args.binary,'serve','--hostname','127.0.0.1','--port',str(port)],
                                         cwd=root,env=env,stdout=log,stderr=log)
                try:
                    def api(path,body=None,method=None):
                        req=Request(f'http://127.0.0.1:{port}'+path,
                                    data=json.dumps(body).encode() if body is not None else None,
                                    headers={'Content-Type':'application/json','x-opencode-directory':str(root),
                                             'Authorization':'Basic '+base64.b64encode(b'opencode:synthetic-engine-only').decode()},method=method)
                        with urlopen(req,timeout=30) as response:
                            raw=response.read();return json.loads(raw) if raw else {}

                    deadline=time.monotonic()+30
                    while True:
                        try:
                            api('/api/info');break
                        except URLError:
                            if time.monotonic()>deadline or process.poll() is not None:
                                raise RuntimeError('Isolated synthetic engine did not become ready')
                            time.sleep(.1)
                    titles={}
                    for name,body in (('overridden',{'title':'GoodMorning · Secretary'}),('native',{})):
                        session=api('/api/session',body)['data']['id']
                        api(f'/api/session/{session}/model',{'model':{'providerID':'synthetic','id':'synthetic'}})
                        api(f'/api/session/{session}/prompt',{'text':'Review my project priorities.'})
                        deadline=time.monotonic()+20
                        while True:
                            active=api('/api/session/active')['data']
                            title=api(f'/api/session/{session}')['data'].get('title')
                            if not active and (name=='overridden' or title=='Review project priorities'):break
                            if time.monotonic()>deadline:
                                raise AssertionError({'stage':name,'title':title,'calls':calls})
                            time.sleep(.1)
                        titles[name]=title
                    assert titles=={'overridden':'GoodMorning · Secretary','native':'Review project priorities'},titles
                    assert calls.count('title')==1,calls
                    before=api(f'/api/session/{session}/message?limit=100')['data']
                    api(f'/api/session/{session}',{'title':''},'PATCH')
                    after=api(f'/api/session/{session}/message?limit=100')['data']
                    assert before==after
                    assert calls.count('title')==2,calls
                    print(json.dumps({'externalModelCalls':0,'realNativeEngine':True,
                        'customTitleDisablesAutoGeneration':True,'untitledSessionAutoGenerates':True,
                        'nativeRegenerationPreservesMessages':True,'syntheticTitleRequests':2}))
                finally:
                    process.terminate();process.wait(timeout=10)
    finally:
        provider.shutdown();provider.server_close()


if __name__=='__main__':main()
