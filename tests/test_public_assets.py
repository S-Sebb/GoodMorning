"""Asset loading order and scoped authentication protection, without private records."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.web.language import page

ROOT=Path(__file__).resolve().parents[1]


class PublicAssetTests(unittest.TestCase):
    def test_response_reader_precedes_page_scripts_and_is_not_duplicated(self):
        source='<html><head><script src="/browser.js" defer></script></head><body></body></html>'
        rendered=page(source,'x')
        self.assertLess(rendered.index('/network.js'),rendered.index('/browser.js'))
        self.assertEqual(page(rendered,'x').count('/network.js'),1)

    def test_nginx_limits_only_credential_post_requests(self):
        source=(ROOT/'deploy/nginx-goodmorning.conf').read_text()
        block=re.search(r'map "\$request_method:\$uri" \$goodmorning_auth_key \{(.*?)\}',source,re.S)[1]
        # Empty keys are not counted: only credential submissions share the per-address limit.
        self.assertEqual(re.findall(r'^\s*(\S+)\s+(\S+);',block,re.M),
                         [('default','""'),('~^POST:/api/auth/(login|password)$','$binary_remote_addr')])
        self.assertRegex(source,r'limit_req_zone \$goodmorning_auth_key zone=goodmorning_auth_submit:')
        proxied=re.search(r'location / \{(.*?)\}',source.split('listen 127.0.0.1:8443',1)[1],re.S)[1]
        self.assertRegex(proxied,r'limit_req zone=goodmorning_auth_submit\b')
        self.assertIn('proxy_pass',proxied)

    # Deployed releases omit android/; the check runs in checkouts and CI.
    @unittest.skipUnless((ROOT/'android').is_dir(),'android/ is not deployed')
    def test_android_app_package_matches_asset_links(self):
        import json
        gradle=(ROOT/'android/app/build.gradle').read_text()
        package=re.search(r"applicationId '([^']+)'",gradle)[1]
        target=json.loads((ROOT/'assets/web/assetlinks.json').read_text())[0]['target']
        self.assertEqual(target['package_name'],package)

    @unittest.skipUnless(shutil.which('node'),'Node is not available')
    def test_shared_response_reader(self):
        result=subprocess.run(['node','--test',str(ROOT/'tests/test_network.mjs')],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
