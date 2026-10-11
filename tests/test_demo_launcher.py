"""Startup checks do not use Firebase, a real webcam, or background servers."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scripts import run_demo as demo


class DemoLauncherTests(unittest.TestCase):
    def test_credential_is_only_accepted_for_team_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.json'
            path.write_text(json.dumps({'type': 'service_account', 'project_id': 'safe-ddacb'}))
            self.assertEqual(demo.credential_path(str(path)), path.resolve())
            path.write_text(json.dumps({'type': 'service_account', 'project_id': 'other'}))
            with self.assertRaisesRegex(ValueError, 'safe-ddacb'):
                demo.credential_path(str(path))

    def test_missing_or_malformed_credentials_have_actionable_errors(self):
        with self.assertRaisesRegex(ValueError, 'Supply --service-account'):
            demo.credential_path('')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.json'
            with self.assertRaisesRegex(ValueError, 'local file path'):
                demo.credential_path(str(path))
            path.write_text('not-json-private-value')
            with self.assertRaisesRegex(ValueError, 'local file path') as error:
                demo.credential_path(str(path))
            self.assertNotIn('private-value', str(error.exception))
            path.write_text('[]')
            with self.assertRaisesRegex(ValueError, 'service-account JSON'):
                demo.credential_path(str(path))

    @patch.object(demo.socket, 'socket')
    def test_occupied_port_and_frontend_port_are_skipped(self, socket_factory):
        sock = socket_factory.return_value.__enter__.return_value
        sock.bind.side_effect = [OSError('in use'), None]
        self.assertEqual(demo.free_port(5300, (5301,)), 5302)
        self.assertEqual([call.args for call in sock.bind.call_args_list],
                         [(('127.0.0.1', 5300),), (('127.0.0.1', 5302),)])

    def test_private_credentials_stay_out_of_frontend(self):
        frontend, backend = demo.child_environments({
            'PATH': '/bin', 'VITE_FIREBASE_PROJECT_ID': 'safe-ddacb',
            'FIREBASE_SERVICE_ACCOUNT': '/old/key', 'GOOGLE_APPLICATION_CREDENTIALS': '/private/key',
            'SAFE_WEB_ORIGINS': '*', 'SAFE_RECORDINGS_ENABLED': 'true',
            'VITE_BROWSER_DETECTOR_ORIGIN': 'https://old-tunnel.test',
        }, '/new/key', 5300, 8100, False, '/private/clips')
        self.assertNotIn('FIREBASE_SERVICE_ACCOUNT', frontend)
        self.assertNotIn('GOOGLE_APPLICATION_CREDENTIALS', frontend)
        self.assertNotIn('SAFE_RECORDINGS_ENABLED', frontend)
        self.assertNotIn('VITE_FIREBASE_PROJECT_ID', backend)
        self.assertEqual(frontend['VITE_BROWSER_DETECTOR_ORIGIN'], 'http://127.0.0.1:8100')
        self.assertEqual(frontend['VITE_FIREBASE_INCIDENTS_COLLECTION'], 'incidents')
        self.assertEqual(backend['SAFE_WEB_ORIGINS'], 'http://127.0.0.1:5300')
        self.assertEqual(backend['FIREBASE_SERVICE_ACCOUNT'], '/new/key')
        self.assertEqual(backend['SAFE_RECORDINGS_ENABLED'], 'false')

    def test_recording_requires_explicit_flag(self):
        _, backend = demo.child_environments({}, '/key', 5300, 8100, True, '/private/clips')
        self.assertEqual(backend['SAFE_RECORDINGS_ENABLED'], 'true')
        self.assertEqual(backend['SAFE_RECORDINGS_DIR'], '/private/clips')

    @patch.object(demo.importlib.util, 'find_spec', return_value=None)
    def test_missing_python_dependencies(self, find_spec):
        with self.assertRaisesRegex(ValueError, 'pip install -r requirements.txt'):
            demo.preflight(Path('/unused'), {})

    @patch.object(demo.importlib.util, 'find_spec', return_value=object())
    @patch.object(demo.shutil, 'which', return_value=None)
    def test_missing_node(self, which, find_spec):
        with self.assertRaisesRegex(ValueError, 'Node.js is missing'):
            demo.preflight(Path('/unused'), {})

    @patch.object(demo, 'urlopen')
    def test_protected_endpoint_is_ready_at_401_without_credentials(self, open_url):
        open_url.side_effect = HTTPError('http://local', 401, 'Unauthorized', {}, io.BytesIO())
        demo.wait_ready(Mock(poll=Mock(return_value=None)), 'http://local', 401)
        self.assertEqual(open_url.call_count, 1)

    @patch.object(demo, 'urlopen')
    def test_failed_service_does_not_report_ready(self, open_url):
        with self.assertRaisesRegex(RuntimeError, 'stopped during startup'):
            demo.wait_ready(Mock(poll=Mock(return_value=1)), 'http://local', 401)
        open_url.assert_not_called()

    @patch.object(demo.time, 'sleep')
    @patch.object(demo.time, 'monotonic', side_effect=[0, 0, 2])
    @patch.object(demo, 'urlopen', side_effect=URLError('offline'))
    def test_startup_timeout(self, open_url, clock, sleep):
        with self.assertRaisesRegex(RuntimeError, 'Timed out'):
            demo.wait_ready(Mock(poll=Mock(return_value=None)), 'http://local', 200, timeout=1)

    def test_cleanup_terminates_and_reaps_both_services(self):
        first, second = Mock(), Mock()
        first.poll.return_value = second.poll.return_value = None
        second.wait.side_effect = [subprocess.TimeoutExpired('test', 30), None]
        demo.stop_children([first, second])
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        first.wait.assert_called_once_with(timeout=30)
        second.kill.assert_called_once()
        self.assertEqual(second.wait.call_count, 2)

    @patch.object(demo, 'credential_path', return_value=Path('/private/key'))
    @patch.object(demo, 'free_port', side_effect=[5300, 8100])
    @patch.object(demo, 'preflight', return_value=('node', Path('/vite.js')))
    @patch.object(demo, 'wait_ready', side_effect=RuntimeError('startup failed'))
    @patch.object(demo.subprocess, 'Popen')
    def test_startup_failure_cleans_up_started_backend(self, popen, ready, preflight, ports, key):
        child = popen.return_value
        child.poll.return_value = None
        self.assertEqual(demo.main(['--service-account', '/private/key']), 1)
        self.assertEqual(popen.call_count, 1)
        child.terminate.assert_called_once()
        child.wait.assert_called_once()

    @patch.object(demo, 'credential_path', return_value=Path('/private/key'))
    @patch.object(demo, 'free_port', side_effect=[5300, 8100])
    @patch.object(demo, 'preflight', return_value=('node', Path('/vite.js')))
    @patch.object(demo.subprocess, 'Popen')
    def test_check_does_not_start_processes(self, popen, preflight, ports, key):
        self.assertEqual(demo.main(['--check', '--service-account', '/private/key']), 0)
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
