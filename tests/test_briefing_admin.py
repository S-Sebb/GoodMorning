"""SSH password diagnostics must not disclose or change account secrets."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import Accounts
from goodmorning.security.briefing_admin import main


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


if __name__=='__main__':unittest.main()
