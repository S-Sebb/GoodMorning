"""The server's maintenance hooks never interrupt work and always resume the website."""
import importlib.util
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
        self.versions = ['3.14.8', '3.14.8']
        for name, value in {
            'STATE': root/'state', 'HOLD': root/'state/hold.json',
            'clients': lambda: (['a'*32], 'store', self.gateway, {}, self.pause),
            'python_version': lambda: self.versions.pop(0),
            'subprocess': mock.Mock(), 'wait_ready': mock.Mock(return_value=None),
            'urlopen': mock.MagicMock(return_value=mock.MagicMock(status=200)),
        }.items():
            patcher = mock.patch.object(maintain, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in {'wait_idle': lambda idle, timeout: None, 'reserve': mock.Mock()}.items():
            patcher = mock.patch.object(maintain.native, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_hold_python_and_finish_resume_the_website(self):
        self.assertEqual(maintain.hold(), 0)
        self.assertEqual(self.pause.state['by'], maintain.BY)
        self.assertTrue(maintain.HOLD.exists())
        self.assertEqual(maintain.python(), 0)
        self.assertEqual(maintain.finish(), 0)
        self.assertIsNone(self.pause.state)
        self.gateway.clear_ticket.assert_called_once()
        self.assertFalse(maintain.HOLD.exists())
        self.assertEqual(maintain.finish(), 0, 'finish is safe to repeat')
        self.gateway.clear_ticket.assert_called_once()

    def test_changed_python_asks_for_a_reboot_and_needs_a_hold(self):
        with self.assertRaises(SystemExit):
            maintain.python()
        maintain.subprocess.run.assert_not_called()
        maintain.hold()
        self.versions = ['3.14.8', '3.14.9']
        self.assertEqual(maintain.python(), maintain.PYTHON_CHANGED)
        self.assertTrue(maintain.HOLD.exists(), 'The boot unit finishes after the reboot')

    def test_busy_accounts_resume_at_once_without_a_hold(self):
        maintain.native.wait_idle = lambda idle, timeout: 'A session is busy'
        self.assertEqual(maintain.hold(), maintain.NOT_HELD)
        self.assertIsNone(self.pause.state)
        self.assertFalse(maintain.HOLD.exists())

    def test_someone_elses_pause_and_an_earlier_hold_are_left_alone(self):
        self.pause = Pause(by='GoodMorning agent')
        self.assertEqual(maintain.hold(), maintain.NOT_HELD)
        self.assertEqual(self.pause.state['by'], 'GoodMorning agent')
        maintain.resume('store', self.pause)
        self.assertEqual(self.pause.state['by'], 'GoodMorning agent')
        self.pause = Pause()
        maintain.hold()
        self.assertEqual(maintain.hold(), maintain.NOT_HELD)
        self.assertEqual(self.pause.state['by'], maintain.BY)

    def test_a_crash_while_holding_still_resumes(self):
        maintain.native.reserve = mock.Mock(side_effect=KeyboardInterrupt)
        with self.assertRaises(KeyboardInterrupt):
            maintain.hold()
        self.assertIsNone(self.pause.state)
        self.gateway.clear_ticket.assert_called_once()
        self.assertFalse(maintain.HOLD.exists())


class MaintenanceUnitTests(unittest.TestCase):
    def test_deployments_install_only_the_boot_unit(self):
        helper = maintain.native
        self.assertEqual(helper.MAINTENANCE_UNITS, ('goodmorning-maintenance-boot.service',))
        for unit in helper.OBSOLETE_UNITS:
            self.assertNotIn(unit, helper.UNITS)
            self.assertFalse((ROOT/'deploy'/unit).exists())
        boot = (ROOT/'deploy/goodmorning-maintenance-boot.service').read_text()
        self.assertIn('/opt/goodmorning/current/deploy/maintain.py finish', boot)
        self.assertIn('ConditionPathExists=/var/lib/goodmorning-maintenance/hold.json', boot)

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
