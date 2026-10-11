"""Root-only encrypted volume provisioning; gocryptfs owns encryption, not custom code."""
import argparse
import os
from pathlib import Path
import pwd
import re
import secrets
import subprocess

from .briefing_accounts import encrypted_mount


def locations(root, identifier):
    if identifier!='accounts' and not re.fullmatch('[a-f0-9]{32}',identifier):
        raise ValueError('Use accounts or an immutable account ID')
    root=Path(root).absolute()
    if root.resolve()!=root:
        raise ValueError('Vault root cannot contain symlinks')
    return root/'cipher'/identifier,root/'keys'/(identifier+'.key'),root/'live'/identifier


def command(args):
    # A mounted daemon must not inherit captured pipes: communicate() would wait
    # for the daemon instead of the successful mounting parent.
    result=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
    # gocryptfs init can print its master key. Never return stdout/stderr.
    if result.returncode:
        raise ValueError('Encrypted volume operation failed; inspect status locally without sharing keys')


def initialize(root,identifier):
    cipher,key,live=locations(root,identifier)
    if cipher.exists() or key.exists() or live.exists():
        raise ValueError('Volume paths already exist; inspect them, never overwrite')
    for parent in (cipher.parent,key.parent):
        parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        os.chmod(parent,0o700)
    live.parent.mkdir(parents=True,mode=0o711,exist_ok=True)
    os.chmod(live.parent,0o711)
    cipher.mkdir(mode=0o700)
    # The empty underlying mountpoint stays root-owned/unwritable to agent UIDs.
    live.mkdir(mode=0o700)
    with key.open('x') as stream:
        stream.write(secrets.token_urlsafe(48)+'\n')
    os.chmod(key,0o600)
    command(['gocryptfs','-q','-nosyslog','-init','-passfile',str(key),str(cipher)])


def mount(root,identifier):
    cipher,key,live=locations(root,identifier)
    if os.path.ismount(live):
        encrypted_mount(live)
        return live
    if any(p.is_symlink() or p.resolve()!=p for p in (cipher,key,live)):
        raise ValueError('Unsafe volume path')
    if key.stat().st_uid!=0 or key.stat().st_mode&0o077 or live.stat().st_uid!=0 or live.stat().st_mode&0o077:
        raise ValueError('Key and underlying mountpoint must be private to root')
    if any(live.iterdir()):
        raise ValueError('Underlying mountpoint is not empty; preserve and inspect it')
    command(['gocryptfs','-q','-nosyslog','-allow_other','-passfile',str(key),str(cipher),str(live)])
    return encrypted_mount(live)


def provision_user(root,identifier):
    live=mount(root,identifier)
    name='gm_'+identifier[:12]
    try:
        user=pwd.getpwnam(name)
    except KeyError:
        command(['useradd','--system','--no-create-home','--home-dir',str(live/'home'),'--shell','/usr/sbin/nologin',name])
        user=pwd.getpwnam(name)
    if user.pw_dir!=str(live/'home') or user.pw_uid==0:
        raise ValueError('Existing Linux account does not belong to this vault')
    os.chown(live,user.pw_uid,user.pw_gid)
    os.chmod(live,0o700)
    for name in ('home','secretary','tmp','cache','run'):
        target=live/name
        target.mkdir(mode=0o700,exist_ok=True)
        if target.is_symlink():
            raise ValueError('Private runtime cannot contain symlink directories')
        os.chown(target,user.pw_uid,user.pw_gid)
        os.chmod(target,0o700)
    return user.pw_name


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('action',choices=('init','mount','user','check','unmount'))
    parser.add_argument('id')
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Vault management requires root over SSH')
    os.umask(0o077)
    if args.action=='init':
        initialize(args.root,args.id)
    elif args.action=='mount':
        mount(args.root,args.id)
    elif args.action=='user':
        if args.id=='accounts':
            parser.error('The account database volume stays root-only')
        print(provision_user(args.root,args.id))
    else:
        live=locations(args.root,args.id)[2]
        encrypted_mount(live)
        if args.action=='unmount':
            command(['fusermount3','-u',str(live)])
    print(f'{args.action}: {args.id}; no keys printed')


if __name__=='__main__':
    main()
