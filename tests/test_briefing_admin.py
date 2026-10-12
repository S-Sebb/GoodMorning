"""SSH password diagnostics must not disclose or change account secrets."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import Accounts
from goodmorning.security.briefing_admin import main, backend_status, server_defaults


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Accounts(self.root,testing=True,n=1024)
        self.secret='synthetic-private-password1'
        self.store.create('test-user',self.secret)

    def check(self,secret,uid=0):
        output=io.StringIO()
        with patch('sys.argv',['briefing_admin.py','--account-mount',str(self.root),'check','test-user']), \
             patch('goodmorning.security.briefing_admin.Accounts',return_value=self.store), \
             patch('goodmorning.security.briefing_admin.os.geteuid',return_value=uid), \
             patch('goodmorning.security.briefing_admin.getpass.getpass',return_value=secret),redirect_stdout(output):
            result=main()
        self.assertNotIn(secret,output.getvalue())
        return result,output.getvalue()

    def test_matching_check_does_not_reset_password_or_issue_session(self):
        before=self.store.path.read_bytes()
        code,text=self.check(self.secret)
        self.assertEqual(code,0)
        self.assertIn('matches the saved account',text)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_nonmatching_check_returns_failure_without_disclosing_input(self):
        code,text=self.check('wrong-synthetic-password1')
        self.assertEqual(code,1)
        self.assertIn('does not match',text)

    def test_non_root_check_is_refused(self):
        with self.assertRaises(SystemExit):self.check(self.secret,uid=1000)

    def test_backend_check_fails_for_unprovisioned_without_modifying_accounts(self):
        (self.root/'backends.json').write_text('{}')
        before=self.store.path.read_bytes()
        output=io.StringIO()
        with redirect_stdout(output):
            code=backend_status(self.store,'test-user','gm.example.test')
        self.assertEqual(code,1)
        self.assertIn('setup is incomplete',output.getvalue())
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_backend_check_probes_all_pages_without_mutations_or_secrets(self):
        output=io.StringIO()
        with patch('goodmorning.security.briefing_gateway.Gateway') as gateway,redirect_stdout(output):
            gateway.return_value.proxy.return_value=(200,{'Content-Type':'text/html'},b'<html>synthetic</html>')
            self.assertEqual(backend_status(self.store,'test-user','gm.example.test'),0)
        self.assertEqual([call.args[2] for call in gateway.return_value.proxy.call_args_list],['/gm.html','/gn.html','/chat'])
        self.assertTrue(all(call.args[3]=='GET' for call in gateway.return_value.proxy.call_args_list))
        self.assertIn('No model request was sent',output.getvalue())

    def test_backend_check_hides_exception_text_and_rejects_non_html(self):
        for failure in (RuntimeError(self.secret),None):
            output=io.StringIO()
            with patch('goodmorning.security.briefing_gateway.Gateway') as gateway,redirect_stdout(output):
                gateway.return_value.proxy.side_effect=failure
                gateway.return_value.proxy.return_value=(200,{'Content-Type':'application/json'},b'{}')
                self.assertEqual(backend_status(self.store,'test-user','gm.example.test'),1)
            self.assertNotIn(self.secret,output.getvalue())

    def test_create_reports_incomplete_provisioning_with_failure_exit(self):
        output=io.StringIO()
        (self.root/'backends.json').write_text('{}')
        with patch('sys.argv',['briefing_admin.py','--account-mount',str(self.root),'create','new-user']), \
             patch('goodmorning.security.briefing_admin.Accounts',return_value=self.store), \
             patch('goodmorning.security.briefing_admin.os.geteuid',return_value=0), \
             patch('goodmorning.security.briefing_admin.server_defaults',return_value={'model':'deepseek-flash'}), \
             patch('goodmorning.security.briefing_admin.getpass.getpass',return_value=self.secret),redirect_stdout(output):
            self.assertEqual(main(),1)
        self.assertIn('setup is incomplete',output.getvalue())
        self.assertNotIn(self.secret,output.getvalue())
        with self.store.db() as db:
            identifier=db.execute('SELECT id FROM users WHERE name=?',('new-user',)).fetchone()[0]
        self.assertEqual(self.store.website_model(identifier),'deepseek-flash')

    def test_create_without_server_defaults_does_not_create_login_or_request_password(self):
        output=io.StringIO()
        with patch('sys.argv',['briefing_admin.py','--account-mount',str(self.root),'create','new-user']), \
             patch('goodmorning.security.briefing_admin.Accounts',return_value=self.store), \
             patch('goodmorning.security.briefing_admin.os.geteuid',return_value=0), \
             patch('goodmorning.security.briefing_admin.getpass.getpass') as prompt,redirect_stdout(output):
            self.assertEqual(main(),1)
        prompt.assert_not_called()
        with self.store.db() as db:
            self.assertIsNone(db.execute('SELECT id FROM users WHERE name=?',('new-user',)).fetchone())

    def test_server_defaults_validate_private_policy_without_disclosing_key(self):
        from types import SimpleNamespace
        path=self.root/'server-defaults.json'
        value={'model':'muse-spark','providerID':'opencode-go','credential':{'type':'key','key':'synthetic-provider-secret'}}
        path.write_text(json.dumps(value));path.chmod(0o600)
        info=SimpleNamespace(st_mode=path.stat().st_mode,st_uid=0,st_size=path.stat().st_size)
        with patch('goodmorning.security.briefing_admin.os.fstat',return_value=info):
            self.assertEqual(server_defaults(self.store),value)
            value['providerID']='different-provider';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'Invalid server defaults'):server_defaults(self.store)
        info.st_mode |= 0o044
        with patch('goodmorning.security.briefing_admin.os.fstat',return_value=info):
            with self.assertRaisesRegex(ValueError,'Unsafe server defaults'):server_defaults(self.store)

    def test_server_defaults_refuse_symlink(self):
        (self.root/'server-defaults.json').symlink_to(self.root/'accounts.sqlite')
        with self.assertRaises(OSError):server_defaults(self.store)


if __name__=='__main__':unittest.main()
