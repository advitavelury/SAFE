"""Run the local React dashboard and authenticated browser-frame detector."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('cv2', 'numpy', 'PIL', 'ultralytics', 'fastapi', 'uvicorn',
           'firebase_admin', 'imageio_ffmpeg')
PRIVATE_ENV = ('FIREBASE_SERVICE_ACCOUNT', 'GOOGLE_APPLICATION_CREDENTIALS')


def credential_path(value):
    if not value:
        raise ValueError('Supply --service-account /path/to/key.json or FIREBASE_SERVICE_ACCOUNT.')
    path = Path(value).expanduser().resolve()
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        raise ValueError('Cannot read the service-account JSON. Check its local file path.') from None
    if not isinstance(data, dict) or data.get('type') != 'service_account' or data.get('project_id') != 'safe-ddacb':
        raise ValueError('The credential must be a service-account JSON for safe-ddacb.')
    return path


def free_port(first, excluded=()):
    for port in range(first, min(first + 20, 65536)):
        if port in excluded:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise ValueError(f'No free local port near {first}. Choose another port with the command options.')


def child_environments(base, key, frontend_port, backend_port, record, recordings_dir):
    # Backend credentials must never be injected into the frontend toolchain.
    frontend = {k: v for k, v in base.items() if k not in PRIVATE_ENV
                and not k.startswith('SAFE_')}
    frontend.update(VITE_BROWSER_DETECTOR_ORIGIN=f'http://127.0.0.1:{backend_port}',
                    VITE_MEDIA_API_ORIGIN='', VITE_FIREBASE_INCIDENTS_COLLECTION='incidents')
    backend = {k: v for k, v in base.items() if not k.startswith('VITE_')}
    backend.update(FIREBASE_SERVICE_ACCOUNT=str(key),
                   SAFE_WEB_ORIGINS=f'http://127.0.0.1:{frontend_port}',
                   SAFE_RECORDINGS_ENABLED='true' if record else 'false',
                   SAFE_RECORDINGS_DIR=str(recordings_dir),
                   PYTHONDONTWRITEBYTECODE='1', YOLO_AUTOINSTALL='false')
    return frontend, backend


def preflight(root, frontend_env):
    missing = [name for name in MODULES if importlib.util.find_spec(name) is None]
    if missing:
        raise ValueError('Missing Python modules: ' + ', '.join(missing)
                         + '. Activate your virtual environment and run python -m pip install -r requirements.txt.')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node.js is missing. Install Node.js and run npm ci in front-end.')
    frontend = root / 'front-end'
    vite = frontend / 'node_modules/vite/bin/vite.js'
    if not vite.is_file():
        raise ValueError('Frontend dependencies are missing. Run npm ci in front-end.')
    model = root / 'backend/detection/yolo26s-pose.pt'
    if not model.is_file() or model.stat().st_size < 1024:
        raise ValueError('The tracked YOLO pose model is missing or incomplete. Pull the complete repository.')
    # Use Vite's own dotenv precedence/expansion, not a separate .env parser.
    result = subprocess.run([node, str(frontend / 'scripts/check-demo.mjs')],
                            cwd=frontend, env=frontend_env, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stdout.strip() or 'Firebase web configuration check failed. See README.md.')
    return node, vite


def wait_ready(process, url, expected, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('A demo service stopped during startup. Check its error above.')
        try:
            with urlopen(url, timeout=1) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
            error.close()
        except (URLError, TimeoutError, OSError):
            time.sleep(0.2)
            continue
        if status == expected:
            return
        time.sleep(0.2)
    raise RuntimeError('Timed out waiting for a demo service. Check the startup logs above.')


def stop_children(children):
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
    for process in reversed(children):
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def port_number(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError('Use a port between 1024 and 65535.')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-account', default=os.environ.get('FIREBASE_SERVICE_ACCOUNT'))
    parser.add_argument('--record', action='store_true', help='Enable opt-in local red-event clips.')
    parser.add_argument('--recordings-dir', type=Path, default=Path.home() / '.safe/recordings')
    parser.add_argument('--frontend-port', type=port_number, default=5173)
    parser.add_argument('--backend-port', type=port_number, default=8001)
    parser.add_argument('--check', action='store_true', help='Check local setup without starting servers or a camera.')
    args = parser.parse_args(argv)
    children = []
    try:
        key = credential_path(args.service_account)
        recordings = args.recordings_dir.expanduser().resolve()
        if args.record and (recordings == ROOT or ROOT in recordings.parents):
            raise ValueError('Choose a recordings directory outside the repository.')
        frontend_port = free_port(args.frontend_port)
        backend_port = free_port(args.backend_port, (frontend_port,))
        frontend_env, backend_env = child_environments(os.environ, key, frontend_port,
                                                       backend_port, args.record, recordings)
        node, vite = preflight(ROOT, frontend_env)
        if args.check:
            print('Local configuration checks passed. Firebase sign-in, permissions and detection still need a live check.')
            return 0
        backend = subprocess.Popen([sys.executable, '-m', 'uvicorn',
                                    'backend.browser_camera_api:create_app', '--factory',
                                    '--host', '127.0.0.1', '--port', str(backend_port),
                                    '--workers', '1', '--no-access-log'], cwd=ROOT, env=backend_env)
        children.append(backend)
        backend_url = f'http://127.0.0.1:{backend_port}'
        wait_ready(backend, backend_url + '/api/incidents/startup-check/clip', 401)
        frontend = subprocess.Popen([node, str(vite), '--host', '127.0.0.1',
                                     '--port', str(frontend_port), '--strictPort'],
                                    cwd=ROOT / 'front-end', env=frontend_env)
        children.append(frontend)
        dashboard_url = f'http://127.0.0.1:{frontend_port}'
        wait_ready(frontend, dashboard_url, 200)
        print(f'\nSAFE dashboard: {dashboard_url}\nLocal detector: {backend_url}', flush=True)
        print('Sign in as approved staff (admin or operator), connect webcam, then Start detection.', flush=True)
        print('Recording available (checkbox still required).' if args.record else 'Recording disabled.', flush=True)
        print('Ctrl+C stops both services. Stop detection in the dashboard first to finish any clip.\n', flush=True)
        while all(process.poll() is None for process in children):
            time.sleep(0.5)
        raise RuntimeError('A demo service exited. Both services have been stopped; check the logs above.')
    except KeyboardInterrupt:
        print('\nStopping SAFE demo...')
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f'SAFE startup: {error}', file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == '__main__':
    def stop_on_signal(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_signal)
    raise SystemExit(main())
