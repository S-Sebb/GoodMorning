"""Synthetic accounts only: session, password and admin boundaries."""
import hashlib
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import Accounts, Denied, Limited, encrypted_mount, REMEMBER_SECONDS, SESSION_SECONDS, password

SECRET='temporary-secret-for-tests1'


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.time=10000
        self.store=Accounts(self.root,testing=True,n=1024,now=lambda:self.time)
        self.id=self.store.create('test-user',SECRET)
        token,_=self.store.anonymous('gm.example.test')
        self.pre=self.store.session(token,'gm.example.test')

    def login(self,remember=False):
        token,_,temporary=self.store.login('Test-User',SECRET,'gm.example.test','192.0.2.1',self.pre,remember=remember)
        return token,self.store.session(token,'gm.example.test'),temporary

    def test_production_refuses_unencrypted_storage_and_low_password_cost(self):
        with self.assertRaises(ValueError): encrypted_mount(self.root)
        with self.assertRaises(ValueError): Accounts(self.root)
        with self.assertRaises(ValueError): Accounts(self.root,n=1024)

    def test_login_rotates_session_and_stores_only_hashes(self):
        token,session,temporary=self.login()
        self.assertTrue(temporary)
        self.assertEqual(session['user_id'],self.id)
        self.assertNotEqual(session['hash'],self.pre['hash'])
        with self.store.db() as db:
            self.assertIsNone(db.execute('SELECT * FROM sessions WHERE hash=?',(self.pre['hash'],)).fetchone())
            self.assertEqual(db.execute('SELECT hash FROM sessions WHERE user_id=?',(self.id,)).fetchone()[0],hashlib.sha256(token.encode()).hexdigest())
        raw=self.store.path.read_bytes()
        self.assertNotIn(SECRET.encode(),raw)
        self.assertNotIn(token.encode(),raw)

    def test_host_idle_and_absolute_expiry(self):
        token,session,_=self.login()
        with self.assertRaises(Denied): self.store.session(token,'gn.example.test')
        self.time+=1801
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')
        self.time=10000
        self.time+=43201
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')

    def test_reset_requires_current_password_and_revokes_other_sessions(self):
        token,session,_=self.login()
        other,_=self.store.anonymous('gn.example.test')
        pre=self.store.session(other,'gn.example.test')
        second,_,_=self.store.login('test-user',SECRET,'gn.example.test','192.0.2.2',pre)
        with self.assertRaises(Denied): self.store.change_password(session,'wrong','permanent-password-new1','192.0.2.1')
        replacement,_=self.store.change_password(session,SECRET,'permanent-password-new1','192.0.2.1')
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')
        with self.assertRaises(Denied): self.store.session(second,'gn.example.test')
        current=self.store.session(replacement,'gm.example.test')
        self.assertFalse(current['temporary'])

    def test_remembered_session_has_fixed_60_day_expiry_without_idle_timeout(self):
        token,session,_=self.login(remember=True)
        self.assertEqual(session['remembered'],1)
        self.assertEqual(session['expires']-session['created'],REMEMBER_SECONDS)
        self.time+=REMEMBER_SECONDS-1
        self.assertEqual(self.store.session(token,'gm.example.test')['expires'],session['expires'])
        with self.assertRaises(Denied): self.store.session(token,'gn.example.test')
        self.time+=1
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')

    def test_ordinary_session_absolute_expiry_despite_activity(self):
        token,session,_=self.login()
        self.assertEqual(session['remembered'],0)
        self.assertEqual(session['expires']-session['created'],SESSION_SECONDS)
        for _ in range(SESSION_SECONDS//900-1):
            self.time+=900
            self.store.session(token,'gm.example.test')
        self.time=session['expires']
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')

    def test_password_replacement_preserves_remember_choice_and_revokes_old_token(self):
        token,session,_=self.login(remember=True)
        replacement,_=self.store.change_password(session,SECRET,'permanent-password-new1','192.0.2.1')
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')
        current=self.store.session(replacement,'gm.example.test')
        self.assertEqual(current['remembered'],1)
        self.assertEqual(current['expires']-current['created'],REMEMBER_SECONDS)
        self.store.logout(current)
        with self.assertRaises(Denied): self.store.session(replacement,'gm.example.test')

    def test_admin_reset_revokes_remembered_session(self):
        token,_,_=self.login(remember=True)
        self.store.administer('test-user',temporary='replacement-temporary-secret1')
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')

    def test_cleanup_does_not_delete_idle_remembered_sessions(self):
        token,_,_=self.login(remember=True)
        self.time+=1801
        self.store.anonymous('gm.example.test')
        self.assertEqual(self.store.session(token,'gm.example.test')['user_id'],self.id)

    def test_remember_choice_is_strictly_boolean(self):
        for value in ('false',1,None):
            with self.assertRaises(ValueError): self.login(remember=value)

    def test_admin_rename_and_recovery_revoke_sessions_without_moving_identity(self):
        token,session,_=self.login()
        self.assertEqual(self.store.administer('test-user',new_name='renamed'),self.id)
        with self.assertRaises(Denied): self.store.session(token,'gm.example.test')
        self.assertEqual(self.store.administer('renamed',temporary='new-temporary-password1'),self.id)
        self.store.administer('renamed',enabled=False)
        with self.assertRaises(Denied): self.store.login('renamed','new-temporary-password1','gm.example.test','192.0.2.1',self.pre)

    def test_invalid_username_and_weak_password(self):
        for name in ('../other','a','测试','name with spaces'):
            with self.assertRaises(ValueError): self.store.create(name,SECRET)
        with self.assertRaises(ValueError): self.store.create('valid','short')

    def test_admin_password_check_is_read_only_and_checks_reset_password(self):
        before=self.store.path.read_bytes()
        self.assertTrue(self.store.check_password('test-user',SECRET))
        self.assertFalse(self.store.check_password('test-user','not-the-saved-password1'))
        self.assertEqual(self.store.path.read_bytes(),before)
        self.store.administer('test-user',temporary='new-temporary-password1')
        self.assertFalse(self.store.check_password('test-user',SECRET))
        self.assertTrue(self.store.check_password('test-user','new-temporary-password1'))

    def test_unicode_password_change_and_same_password_rejection(self):
        token,session,_=self.login()
        secret='新的永久密码，包含字母和数字123。'
        token,_=self.store.change_password(session,SECRET,secret,'192.0.2.1')
        session=self.store.session(token,'gm.example.test')
        with self.assertRaises(ValueError):
            self.store.change_password(session,secret,secret,'192.0.2.1')
        token,_=self.store.change_password(session,secret,'second-permanent-password1','192.0.2.1')
        self.assertEqual(self.store.session(token,'gm.example.test')['user_id'],self.id)

    def test_rate_limits_persist_across_restart_and_do_not_store_ip(self):
        for _ in range(5):
            with self.assertRaises(Denied): self.store.login('unknown','wrong','gm.example.test','192.0.2.1',self.pre)
        reopened=Accounts(self.root,testing=True,n=1024,now=lambda:self.time)
        with self.assertRaises(Limited): reopened.login('unknown','wrong','gm.example.test','192.0.2.1',self.pre)
        self.assertNotIn(b'192.0.2.1',self.store.path.read_bytes())
        self.time+=901
        with self.assertRaises(Denied) as result: reopened.login('unknown','wrong','gm.example.test','192.0.2.1',self.pre)
        self.assertNotIsInstance(result.exception,Limited)

    def test_new_password_policy_has_inclusive_limits_and_requires_letters_and_digits(self):
        for value in ('a12345', 'abcde1', 'a1'+'x'*30, 'a1!@#$', '中文1234', 'a1'+'🙂'*30):
            with self.subTest(value=value): self.assertEqual(password(value),value)
        for value in ('a1234', 'a1'+'x'*31, 'abcdef', '123456', '12345!', 'abcde!', '\x00abc12', '', None, 123456):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): password(value)

    def test_policy_is_enforced_for_creation_ssh_reset_and_web_replacement(self):
        token,session,_=self.login()
        for value in ('abcdef','123456','abc12','a1'+'x'*31):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.store.create('invalid-user',value)
                with self.assertRaises(ValueError): self.store.administer('test-user',temporary=value)
                with self.assertRaises(ValueError): self.store.change_password(session,SECRET,value,'192.0.2.1')
        self.assertTrue(self.store.check_password('test-user',SECRET))
        self.assertEqual(self.store.session(token,'gm.example.test')['revision'],session['revision'])

    def test_six_character_password_is_accepted_on_all_password_write_paths(self):
        self.store.create('short-user','a12345')
        self.store.administer('test-user',temporary='abcde1')
        self.assertTrue(self.store.check_password('test-user','abcde1'))
        token,_,_=self.store.login('test-user','abcde1','gm.example.test','192.0.2.1',self.pre)
        session=self.store.session(token,'gm.example.test')
        token,_=self.store.change_password(session,'abcde1','1abcde','192.0.2.1')
        self.assertTrue(self.store.check_password('test-user','1abcde'))


if __name__=='__main__':
    unittest.main()
