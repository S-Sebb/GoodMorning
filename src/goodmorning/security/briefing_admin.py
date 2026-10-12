"""SSH-only account administration. Secrets are read with getpass, never argv/logs."""
import argparse
import getpass
import os
from pathlib import Path

from .briefing_accounts import Accounts, username


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
    parser.add_argument('action',choices=('create','rename','reset','disable','enable','list','check','check-backend'))
    parser.add_argument('username',nargs='?')
    parser.add_argument('--new-name')
    parser.add_argument('--gm-host',default='gm.love765.me')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('SSH administration requires root')
    store = Accounts(args.account_mount)
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
    if args.action in ('create','reset'):
        secret = getpass.getpass('Temporary password (6–32 characters, with a letter and digit): ')
        if secret != getpass.getpass('Repeat temporary password: '):
            parser.error('Passwords do not match')
        identifier = store.create(args.username,secret) if args.action=='create' else store.administer(args.username,temporary=secret)
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
