"""The daily maintenance routine never interrupts work and always resumes the website."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintain', ROOT/'deploy/maintain.py')
maintain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintain)


class Pause:
    def __init__(self, by=None):
        self.state = {'enabled': True, 'by': by} if by else None

    def get_state(self, store):
        return self.state

    def set_state(self, store, enabled, *, reason=None, by=None):
        self.state = {'enabled': True, 'by': by} if enabled else None


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.pause, self.gateway = Pause(), mock.Mock()
        self.boot = 'boot-1'
        self.updates = {'apt': {'upgraded': ['openssl'], 'notUpgraded': []},
                        'python': {'from': '3.14.8', 'to': '3.14.8'}}
        self.reasons = []
        for name, value in {
            'STATE': root/'state', 'HOLD': root/'state/hold.json', 'LOGS': root/'logs',
            'clients': lambda: (['a'*32], 'store', self.gateway, {}, self.pause),
            'boot_id': lambda: self.boot,
            'update_apt': lambda: self.updates['apt'],
            'update_python': mock.Mock(side_effect=lambda: self.updates['python']),
            'update_siyuan': lambda: {'updated': False},
            'reboot_reasons': lambda: list(self.reasons),
            'subprocess': mock.Mock(), 'wait_ready': mock.Mock(return_value=None), 'urlopen': mock.MagicMock(return_value=mock.MagicMock(status=200)),
        }.items():
            patcher = mock.patch.object(maintain, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in {'wait_idle': lambda idle, timeout: None, 'reserve': mock.Mock()}.items():
            patcher = mock.patch.object(maintain.native, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.maintain = maintain

    def report(self):
        return json.loads(next(maintain.LOGS.glob('*.json')).read_text())

    def rebooted(self):
        return any(call.args[0] == ['systemctl', 'reboot'] for call in maintain.subprocess.run.call_args_list)

    def test_idle_without_reboot_reasons_updates_and_resumes(self):
        self.assertEqual(maintain.run(), 0)
        self.assertIsNone(self.pause.state)
        self.gateway.clear_ticket.assert_called_once()
        self.assertFalse(self.rebooted() or maintain.HOLD.exists())
        report = self.report()
        self.assertEqual((report['result'], report['idle']), ('ok', True))
        self.assertEqual([s['step'] for s in report['steps']],
                         ['wait for idle', 'ubuntu and docker packages', 'goodmorning python', 'siyuan'])

    def test_busy_accounts_resume_at_once_and_defer_restarts(self):
        maintain.native.wait_idle = lambda idle, timeout: 'A session is busy'
        self.reasons = ['A newer kernel is installed']
        self.assertEqual(maintain.run(), 0)
        maintain.update_python.assert_not_called()
        self.assertFalse(self.rebooted())
        self.assertIsNone(self.pause.state)
        report = self.report()
        self.assertEqual((report['idle'], report['busy'], report['restartDeferred']), (False, 'A session is busy', True))

    def test_reboot_keeps_the_hold_until_the_next_boot_finishes(self):
        self.updates['python'] = {'from': '3.14.8', 'to': '3.14.9'}
        self.assertEqual(maintain.run(), 0)
        self.assertTrue(self.rebooted())
        self.assertEqual(self.pause.state['by'], maintain.BY)
        self.gateway.clear_ticket.assert_not_called()
        self.assertEqual(maintain.finish(), 0, 'The same boot must leave the hold for after the reboot')
        self.assertTrue(maintain.HOLD.exists())
        self.boot = 'boot-2'
        self.assertEqual(maintain.finish(), 0)
        self.assertIsNone(self.pause.state)
        self.gateway.clear_ticket.assert_called_once_with({'maintenance': self.report()['date']})
        self.assertFalse(maintain.HOLD.exists())
        report = self.report()
        self.assertEqual((report['result'], report['rebooted']), ('ok', True))
        self.assertIn('GoodMorning Python changed', report['rebootReasons'])

    def test_failed_packages_never_reboot(self):
        self.reasons = ['Ubuntu requires a reboot']
        maintain.update_apt = mock.Mock(side_effect=RuntimeError('dpkg failed'))
        self.assertEqual(maintain.run(), 1)
        self.assertFalse(self.rebooted())
        self.assertIsNone(self.pause.state)
        self.assertEqual(self.report()['result'], 'failed: ubuntu and docker packages')

    def test_someone_elses_pause_is_left_alone(self):
        self.pause = Pause(by='GoodMorning agent')
        self.assertEqual(maintain.run(), 0)
        self.assertEqual(self.pause.state['by'], 'GoodMorning agent')
        self.assertTrue(self.report()['result'].startswith('skipped'))
        maintain.resume('store', self.pause)
        self.assertEqual(self.pause.state['by'], 'GoodMorning agent')

    def test_a_crash_mid_run_still_resumes(self):
        maintain.update_siyuan = mock.Mock(side_effect=KeyboardInterrupt)
        with self.assertRaises(KeyboardInterrupt):
            maintain.run()
        self.assertIsNone(self.pause.state)
        self.gateway.clear_ticket.assert_called_once()
        self.assertFalse(maintain.HOLD.exists())

    def test_reboot_reasons_read_needrestart(self):
        output = 'NEEDRESTART-KSTA: 3\nNEEDRESTART-SVC: nginx.service\nNEEDRESTART-SVC: cron.service\n'
        # setUp replaced reboot_reasons and subprocess; test an unpatched copy.
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        with mock.patch.object(fresh.subprocess, 'run', return_value=mock.Mock(stdout=output)), \
                mock.patch.object(fresh, 'Path', return_value=mock.Mock(exists=lambda: False)):
            self.assertEqual(fresh.reboot_reasons(), ['A newer kernel is installed',
                                                      'Services use replaced libraries: nginx.service, cron.service'])


class MaintenanceUnitTests(unittest.TestCase):
    def test_deployments_install_and_enable_the_daily_timer(self):
        helper = maintain.native
        for unit in ('goodmorning-maintenance.service', 'goodmorning-maintenance.timer',
                     'goodmorning-maintenance-boot.service'):
            self.assertIn(unit, helper.UNITS)
            self.assertTrue((ROOT/'deploy'/unit).is_file())
        self.assertIn('OnCalendar=*-*-* 05:00:00 Asia/Shanghai', (ROOT/'deploy/goodmorning-maintenance.timer').read_text())
        for unit in ('goodmorning-maintenance.service', 'goodmorning-maintenance-boot.service'):
            self.assertIn('/opt/goodmorning/current/deploy/maintain.py', (ROOT/'deploy'/unit).read_text())

    def test_new_units_install_without_a_rollback_copy(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as name:
            root = Path(name)
            (root/'backup').mkdir()
            (root/'source.timer').write_text('new')
            target = root/'target.timer'
            self.assertTrue(maintain.native.install(root/'source.timer', target, root/'backup'))
            self.assertEqual(target.read_text(), 'new')
            self.assertFalse((root/'backup'/'target.timer').exists())
            self.assertFalse(maintain.native.install(root/'source.timer', target, root/'backup'))


if __name__ == '__main__':
    unittest.main()
