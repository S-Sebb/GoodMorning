"""Hosted account provisioning resumes safely and never prints secrets."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import Accounts
from goodmorning.security.briefing_gateway import Gateway
from goodmorning.security import briefing_provision
from goodmorning.web.models import MODELS

DEFAULTS = {'model':'deepseek-flash','providerID':'opencode-go','credential':{'type':'key','key':'synthetic-provider-secret'}}


class Engine:
    """A fake account engine that offers models only after the credential is registered."""
    def __init__(self, connected=False):
        self.connected, self.writes = connected, []

    def request(self, path, body=None, method=None):
        if path == '/api/model':
            models = [{'providerID':entry['providerID'],'id':entry['id']} for entry in MODELS.values()]
            return {'data':models if self.connected else []}
        if path == '/api/integration':
            return {'data':[{'id':'opencode-go'}]}
        if path == '/api/credential':
            self.writes.append(body)
            self.connected = True
            return {}
        raise AssertionError(path)


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'live/accounts').mkdir(parents=True)
        self.store = Accounts(self.root/'live/accounts', testing=True, n=1024)
        self.other = {'port':18766,'key':'o'*43}
        (self.store.directory/'backends.json').write_text(json.dumps({'a'*32:self.other}))
        self.units = self.root/'units'
        self.units.mkdir()

    def provision(self, engine):
        def initialize(root, identifier):
            (root/'cipher'/identifier).mkdir(parents=True)
            (root/'live'/identifier).mkdir()
        def provision_user(root, identifier):
            for name in ('home','secretary','tmp','cache','run'):
                (root/'live'/identifier/name).mkdir(exist_ok=True)
            return 'gm_synthetic'
        output = io.StringIO()
        with patch.object(briefing_provision, 'server_defaults', return_value=DEFAULTS), \
             patch.object(briefing_provision, 'backend_status', return_value=0), \
             patch.object(briefing_provision, 'systemctl') as systemctl, \
             patch.object(briefing_provision, 'UNITS', self.units), \
             patch.object(briefing_provision.briefing_vault, 'initialize', side_effect=initialize) as init, \
             patch.object(briefing_provision.briefing_vault, 'provision_user', side_effect=provision_user), \
             patch.object(briefing_provision.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())), \
             patch('goodmorning.security.briefing_runtime.LocalBridge', return_value=engine), redirect_stdout(output):
            result = briefing_provision.provision(self.store, 'new-user', 'gm.example.test', root=self.root)
        self.assertEqual(result, 0)
        for secret in ('synthetic-provider-secret', *self.secrets()):
            self.assertNotIn(secret, output.getvalue())
        return init, systemctl

    def identifier(self):
        with self.store.db() as db:
            return db.execute('SELECT id FROM users WHERE name=?',('new-user',)).fetchone()[0]

    def secrets(self):
        values = [path.read_text().split()[1] for path in self.store.directory.glob('new-user-initial-password-*.txt')]
        config = json.loads((self.root/'live'/self.identifier()/'engine.json').read_text())
        return values+[config['uiPassword'],config['gatewayKey']]

    def test_new_account_gets_handover_runtime_services_credential_and_backend(self):
        engine = Engine()
        self.provision(engine)
        identifier = self.identifier()
        handover, = self.store.directory.glob('new-user-initial-password-*.txt')
        self.assertEqual(handover.stat().st_mode & 0o777, 0o600)
        name, secret = handover.read_text().split()
        self.assertTrue(self.store.check_password(name, secret))
        self.assertEqual(self.store.website_model(identifier), 'deepseek-flash')
        config = json.loads((self.root/'live'/identifier/'engine.json').read_text())
        self.assertNotEqual(config['viewerPort'], self.other['port'])
        self.assertEqual(engine.writes, [{'integrationID':'opencode-go','value':DEFAULTS['credential'],'activate':True}])
        opencode = self.root/'live'/identifier/'home/.config/opencode/opencode.json'
        self.assertEqual(json.loads(opencode.read_text()), {'model':'opencode-go/deepseek-v4.1-flash'})
        drop_in = (self.units/f'goodmorning-account@{identifier}.service.d/identity.conf').read_text()
        self.assertIn('User=gm_synthetic', drop_in)
        self.assertIn('SupplementaryGroups=goodmorning-engine', drop_in)
        listen = (self.units/f'goodmorning-account@{identifier}.socket.d/listen.conf').read_text()
        self.assertIn(f'ListenStream=127.0.0.1:{config["chamberPort"]}', listen)
        registry = json.loads((self.store.directory/'backends.json').read_text())
        self.assertEqual(registry['a'*32], self.other)
        self.assertEqual(registry[identifier], {'port':config['viewerPort'],'key':config['gatewayKey']})
        # The registered entry passes the gateway's own validation.
        self.assertEqual(Gateway(self.store, {'gm.example.test':'gm'}).backend(identifier)['port'], config['viewerPort'])

    def test_rerun_keeps_login_vault_keys_and_credential(self):
        self.provision(Engine())
        identifier = self.identifier()
        config = (self.root/'live'/identifier/'engine.json').read_text()
        engine = Engine(connected=True)
        init, _ = self.provision(engine)
        init.assert_not_called()
        self.assertEqual(engine.writes, [])
        self.assertEqual(len(list(self.store.directory.glob('new-user-initial-password-*.txt'))), 1)
        self.assertEqual((self.root/'live'/identifier/'engine.json').read_text(), config)

    def test_missing_provider_models_stop_before_backend_registration(self):
        class Silent(Engine):
            def request(self, path, body=None, method=None):
                result = super().request(path, body, method)
                self.connected = False
                return result
        with patch.object(briefing_provision.time, 'sleep'), \
             patch.object(briefing_provision.time, 'monotonic', side_effect=[0, 0, 1000]), \
             self.assertRaisesRegex(RuntimeError, 'not offered'):
            self.provision(Silent())
        self.assertNotIn(self.identifier(), json.loads((self.store.directory/'backends.json').read_text()))


if __name__=='__main__':unittest.main()
