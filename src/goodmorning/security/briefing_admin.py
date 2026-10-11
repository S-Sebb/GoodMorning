"""SSH-only account administration. Secrets are read with getpass, never argv/logs."""
import argparse
import getpass
import os
from pathlib import Path

from .briefing_accounts import Accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-mount',type=Path,required=True)
    parser.add_argument('action',choices=('create','rename','reset','disable','enable','list','check'))
    parser.add_argument('username',nargs='?')
    parser.add_argument('--new-name')
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


if __name__=='__main__':
    raise SystemExit(main())
