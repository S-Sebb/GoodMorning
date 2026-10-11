#!/usr/bin/env python3
"""Reload NGINX only after renewal of a GoodMorning domain certificate."""
import os
import subprocess

if {'gm.love765.me','gn.love765.me','sec.love765.me'} & set(os.environ.get('RENEWED_DOMAINS','').split()):
    subprocess.run(['/usr/sbin/nginx','-t'],check=True,capture_output=True)
    subprocess.run(['/bin/systemctl','reload','nginx'],check=True,capture_output=True)
