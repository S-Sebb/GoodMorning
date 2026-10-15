"""SSH-only account administration. Secrets are read with getpass, never argv/logs."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat

from .briefing_accounts import Accounts, username


def server_defaults(store):
    """Read the root-owned hosted policy without printing provider credentials."""
    from goodmorning.web.models import MODELS, model
    store.check()
    path = store.directory/'server-defaults.json'
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 20000:
            raise ValueError('Unsafe server defaults')
        value = json.load(stream)
    if not isinstance(value,dict) or set(value) != {'model','providerID','credential'}:
        raise ValueError('Invalid server defaults')
    selected = model(value['model'])
    credential = value['credential']
    if (value['providerID'] != MODELS[selected]['providerID'] or not isinstance(credential,dict)
            or set(credential) != {'type','key'} or credential['type'] != 'key'
            or not isinstance(credential['key'],str) or not credential['key'].strip()):
        raise ValueError('Invalid server defaults')
    return value


def backend_status(store,name,host):
    """Read-only readiness probe: no queue pumping, model calls or login tokens."""
    from .briefing_gateway import Gateway, BackendPending
    with store.db() as db:
        row = db.execute('SELECT id,enabled FROM users WHERE name=?',(username(name),)).fetchone()
    if not row:
        print('Account not found.')
        return 1
    if not row['enabled']:
        print('Account is disabled.')
        return 1
    gateway = Gateway(store,{host:'gm'})
    try:
        for path in ('/gm.html','/gn.html','/chat'):
            status,headers,data = gateway.proxy(row['id'],host,path,'GET',None,{})
            if status != 200 or not headers.get('Content-Type','').startswith('text/html') or not data:
                print('Secretary backend is not ready; inspect its services over SSH.')
                return 1
    except BackendPending:
        print('Secretary setup is incomplete: provision the isolated runtime and register its backend before handing over access.')
        return 1
    except Exception as error:
        print('Secretary backend check failed ('+type(error).__name__+'); inspect its services over SSH.')
        return 1
    print('Secretary backend is ready: Morning, Evening and Secretary pages respond. No model request was sent.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-mount',type=Path,required=True)
    parser.add_argument('action',choices=('create','rename','reset','disable','enable','list','check','check-backend','pause','resume','pause-status'))
    parser.add_argument('username',nargs='?')
    parser.add_argument('--new-name')
    parser.add_argument('--reason')
    parser.add_argument('--by')
    parser.add_argument('--gm-host',default='gm.love765.me')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('SSH administration requires root')
    store = Accounts(args.account_mount)
    if args.action in ('pause', 'resume', 'pause-status'):
        from . import maintenance as deploy_pause
        if args.action == 'pause':
            state = deploy_pause.set_state(store, True, reason=args.reason, by=args.by)
            print(f"Website paused for deployment; new work receives 503 with Retry-After {deploy_pause.RETRY_AFTER_SECONDS}.")
            return 0
        if args.action == 'resume':
            deploy_pause.set_state(store, False)
            print('Website resumed; new work is accepted again.')
            return 0
        state = deploy_pause.get_state(store)
        if state is None:
            print('Website is live; no deployment pause is enabled.')
        else:
            print(f"Website is paused for deployment (Retry-After {deploy_pause.RETRY_AFTER_SECONDS}).")
        return 0
    if args.action == 'list':
        with store.db() as db:
            for row in db.execute('SELECT id,name,temporary,enabled FROM users ORDER BY name'):
                print(f'{row["id"]} {row["name"]} temporary={row["temporary"]} enabled={row["enabled"]}')
        return
    if not args.username:
        parser.error('Username is required')
    if args.action == 'check-backend':
        return backend_status(store,args.username,args.gm_host)
    if args.action == 'check':
        matches=store.check_password(args.username,getpass.getpass('Password to check (not saved): '))
        print('Password matches the saved account.' if matches else 'Password does not match the saved account.')
        return 0 if matches else 1
    if args.action == 'create':
        try:
            defaults = server_defaults(store)
        except Exception as error:
            print('Server defaults are not ready ('+type(error).__name__+'); configure the encrypted hosted policy before creating accounts.')
            return 1
    if args.action in ('create','reset'):
        secret = getpass.getpass('Temporary password (6–32 characters, with a letter and digit): ')
        if secret != getpass.getpass('Repeat temporary password: '):
            parser.error('Passwords do not match')
        identifier = store.create(args.username,secret) if args.action=='create' else store.administer(args.username,temporary=secret)
        if args.action == 'create':
            store.website_model(identifier,defaults['model'])
            print('New account uses the server-default AI configuration; provision its isolated backend with the encrypted server defaults.')
    elif args.action == 'rename':
        if not args.new_name:
            parser.error('--new-name is required')
        identifier = store.administer(args.username,new_name=args.new_name)
    else:
        identifier = store.administer(args.username,enabled=args.action=='enable')
    print(f'{args.action}: account {identifier}; account storage must be provisioned separately')
    if args.action in ('create','enable'):
        return backend_status(store,args.username,args.gm_host)


if __name__=='__main__':
    raise SystemExit(main())
