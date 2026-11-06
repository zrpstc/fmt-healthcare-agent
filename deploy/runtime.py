#!/usr/bin/env python3
"""One lifecycle for this checkout: application processes, build and managed search."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('workspace-api', 'workspace-web', 'agent-daemon')

class RuntimeFailure(Exception):
    def __init__(self, code):
        self.code = code

def truth(value):
    return str(value).lower() in {'true', '1', 'yes'}

@dataclass
class Config:
    root: Path
    env: dict
    workspace: Path
    python: Path
    web: Path
    uid: int
    gid: int
    user: str
    web_port: int
    api_port: int
    agent_port: int
    managed_search: bool
    agent_enabled: bool

    @classmethod
    def load(cls, root=ROOT, parent_env=None):
        root = Path(root).resolve()
        env = dict(os.environ if parent_env is None else parent_env)
        env.update({k: v for k, v in dotenv_values(root / '.env').items() if v is not None})
        def path(key, default):
            p = Path(env.get(key) or default).expanduser()
            return (root / p).resolve() if not p.is_absolute() else p.resolve()
        workspace, python = path('WGS_WORKSPACE', 'var'), path('WGS_ENV_ROOT', '.venv') / 'bin/python'
        if workspace in {Path('/'), Path.home().resolve(), root} or workspace in root.parents:
            raise RuntimeFailure('INVALID_WORKSPACE')
        owner = root.stat().st_uid or root.parent.stat().st_uid
        account = pwd.getpwnam(env['WGS_RUN_USER']) if env.get('WGS_RUN_USER') else pwd.getpwuid(owner)
        if os.geteuid() not in {0, account.pw_uid}:
            raise RuntimeFailure('WRONG_RUNTIME_USER')
        try:
            ports = [int(env.get(k, str(d))) for k, d in [('WGS_WEB_PORT', 18502), ('WGS_API_PORT', 18503), ('WGS_PORT', 7438)]]
        except ValueError:
            raise RuntimeFailure('INVALID_PORT')
        if any(not 1 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
            raise RuntimeFailure('INVALID_PORT')
        env.update(WGS_APP_ROOT=str(root), WGS_ENV_ROOT=str(python.parent.parent), WGS_WORKSPACE=str(workspace),
                   WGS_WEB_PORT=str(ports[0]), WGS_API_PORT=str(ports[1]), WGS_PORT=str(ports[2]),
                   PATH=str(python.parent) + ':' + env.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
                   NEXT_TELEMETRY_DISABLED='1', NODE_ENV='production', HOME=account.pw_dir,
                   USER=account.pw_name, LOGNAME=account.pw_name,
                   PYTHONPATH=str(root / 'src') + ':' + str(root / 'apps/workspace-api') + (':' + env['PYTHONPATH'] if env.get('PYTHONPATH') else ''))
        env.setdefault('WGS_WEB_HOST', '127.0.0.1')
        env.setdefault('WGS_ELASTICSEARCH_URL', 'http://127.0.0.1:9200')
        env.setdefault('WGS_ELASTICSEARCH_MANAGED', 'true')
        env.setdefault('WGS_ELASTICSEARCH_DOCKER_SOCKET', '/var/run/docker.sock')
        if truth(env['WGS_ELASTICSEARCH_MANAGED']):
            # Partial restarts must inherit the same application credential location as a full start.
            env.update(WGS_ELASTICSEARCH_USERNAME='wgs-platform',
                       WGS_ELASTICSEARCH_PASSWORD_FILE=str(workspace / 'elasticsearch/client-password'),
                       WGS_ELASTICSEARCH_API_KEY='')
        enabled = truth(env['WGS_AGENT_DAEMON_ENABLED']) if 'WGS_AGENT_DAEMON_ENABLED' in env else bool(env.get('OPENAI_API_KEY') or env.get('WGS_LOCAL_LLM_API_KEY'))
        return cls(root, env, workspace, python, root / 'apps/workspace-web', account.pw_uid, account.pw_gid,
                   account.pw_name, *ports, truth(env['WGS_ELASTICSEARCH_MANAGED']), enabled)

    def require_privilege(self, component):
        if self.managed_search and component in {'all', 'elasticsearch'} and os.geteuid() != 0:
            raise RuntimeFailure('ADMIN_REQUIRED')

    def drop_privilege(self):
        if os.geteuid() == 0:
            os.initgroups(self.user, self.gid)
            os.setgid(self.gid)
            os.setuid(self.uid)

def own(path, config, mode):
    os.chmod(path, mode)
    if os.geteuid() == 0:
        os.chown(path, config.uid, config.gid)

def atomic_json(path, data, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.runtime-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(data, handle)
        own(name, config, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

@contextmanager
def deployment_lock(config):
    directory = config.workspace / 'run'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'project-runtime.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        own(path, config, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)

def proc_record(pid):
    p = Path('/proc') / str(pid)
    try:
        stat = (p / 'stat').read_text()
        fields = stat[stat.rfind(')')+2:].split()
        return {'pid': int(pid), 'ppid': int(fields[1]), 'pgid': int(fields[2]), 'start': int(fields[19]),
                'state': fields[0], 'uid': p.stat().st_uid, 'cwd': os.readlink(p / 'cwd'),
                'args': (p / 'cmdline').read_bytes().decode(errors='replace').split('\0')}
    except (OSError, ValueError, IndexError):
        return None

def classify(record, root):
    args, cwd = record['args'], record['cwd']
    web = str(root / 'apps/workspace-web')
    is_uvicorn = 'uvicorn' in args or any(a.endswith('/uvicorn') for a in args)
    if is_uvicorn and 'app.main:app' in args:
        if '--app-dir' in args:
            i = args.index('--app-dir')
            target = Path(args[i+1]) if i+1 < len(args) else Path('/')
            target = target if target.is_absolute() else Path(cwd) / target
            if i+1 < len(args) and target.resolve() == root / 'apps/workspace-api':
                return 'workspace-api'
    if cwd == web and any(a.startswith(('next-server', 'npm run start')) or '/node_modules/next/' in a or a.endswith('/node_modules/.bin/next') for a in args):
        return 'workspace-web'
    if cwd == str(root) and any(a.endswith('/wgs-agent') or a == 'wgs-agent' for a in args) and 'serve' in args:
        return 'agent-daemon'
    return None

def discover(root=ROOT, roles=ROLES):
    records = {}
    for p in Path('/proc').iterdir():
        if p.name.isdigit():
            r = proc_record(p.name)
            if r and r['state'] != 'Z':
                records[r['pid']] = r
    excluded, cursor = {os.getpid()}, os.getppid()
    while cursor in records:
        excluded.add(cursor)
        cursor = records[cursor]['ppid']
    selected = {}
    for pid, r in records.items():
        role = classify(r, root)
        if role in roles and pid not in excluded:
            selected[pid] = {**r, 'role': role}
    while True:
        added = False
        for pid, r in records.items():
            if pid not in selected and pid not in excluded and r['ppid'] in selected:
                selected[pid] = {**r, 'role': selected[r['ppid']]['role']}
                added = True
        if not added:
            return selected

def same_process(record):
    now = proc_record(record['pid'])
    return bool(now and now['state'] != 'Z' and now['start'] == record['start'])

def signal_records(records, sig):
    for record in sorted(records.values(), key=lambda r: r['pid'], reverse=True):
        if not same_process(record):
            continue
        try:
            os.kill(record['pid'], sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            raise RuntimeFailure('PROCESS_PERMISSION_DENIED')

def stop_processes(config, roles, timeout=15):
    records = discover(config.root, roles)
    if any(r['uid'] != os.geteuid() for r in records.values()) and os.geteuid() != 0:
        raise RuntimeFailure('ADMIN_REQUIRED')
    signal_records(records, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while any(same_process(r) for r in records.values()) and time.monotonic() < deadline:
        # Capture late children while an original root is still alive.
        records.update(discover(config.root, roles))
        time.sleep(0.1)
    remaining = {pid: r for pid, r in records.items() if same_process(r)}
    signal_records(remaining, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while any(same_process(r) for r in remaining.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    if discover(config.root, roles) or any(same_process(r) for r in remaining.values()):
        raise RuntimeFailure('PROJECT_PROCESSES_REMAIN')
    cleanup_state(config, roles)
    return len(records)

def cleanup_state(config, roles):
    directory = config.workspace / 'run'
    names = set(roles)
    if 'workspace-api' in roles:
        names.add('workspace-api-preview')
    for name in names:
        # Unlink the directory entry; never follow or trust a PID-file target.
        (directory / (name + '.pid')).unlink(missing_ok=True)
    state = directory / 'project-processes.json'
    if state.exists():
        if set(roles) == set(ROLES):
            state.unlink()
        else:
            try:
                data = json.loads(state.read_text())
                data['services'] = {k: v for k, v in data.get('services', {}).items() if k not in roles}
                atomic_json(state, data, config)
            except (OSError, ValueError):
                raise RuntimeFailure('RUNTIME_STATE_UNREADABLE')

def log_path(config, label):
    directory = config.workspace / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f'project-{label}-{time.time_ns()}.log'
    p.touch(mode=0o600, exist_ok=False)
    own(p, config, 0o600)
    return p

def run_checked(config, args, label, *, timeout=180, env=None, as_user=True, cwd=None):
    path = log_path(config, label)
    try:
        with path.open('ab') as handle:
            result = subprocess.run(args, cwd=cwd or config.root, env=env or config.env, stdin=subprocess.DEVNULL,
                stdout=handle, stderr=handle, timeout=timeout,
                preexec_fn=config.drop_privilege if as_user and os.geteuid() == 0 else None)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeFailure(label.upper().replace('-', '_') + '_FAILED')
    if result.returncode:
        raise RuntimeFailure(label.upper().replace('-', '_') + '_FAILED')

def source_fingerprint(config):
    digest = hashlib.sha256()
    paths = []
    for sub in ['app', 'components', 'lib']:
        for directory, dirs, files in os.walk(config.web / sub):
            dirs[:] = [d for d in dirs if d not in {'node_modules', '.git'} and not d.startswith('.next')]
            paths += [Path(directory) / name for name in files]
    paths += [config.web / name for name in ['next.config.mjs', 'package.json', 'package-lock.json', 'tsconfig.json', 'tailwind.config.ts', 'postcss.config.mjs']]
    paths += list(config.web.glob('.env*'))
    for p in sorted(paths):
        if p.is_file():
            digest.update(str(p.relative_to(config.web)).encode())
            content = p.read_bytes()
            if p.name == 'tsconfig.json':
                try:
                    document = json.loads(content)
                    for key in ['include', 'exclude']:
                        if isinstance(document.get(key), list):
                            document[key] = [v for v in document[key] if '.next' not in v]
                    content = json.dumps(document, sort_keys=True).encode()
                except (ValueError, TypeError):
                    pass
            digest.update(content)
    # Credential values are never published or included in status output.
    digest.update(json.dumps([config.api_port, config.env.get('WGS_WEB_PROXY_TIMEOUT_MS')]).encode())
    return digest.hexdigest()

def verify_build(config, dist):
    directory = config.web / dist
    try:
        if not (directory / 'BUILD_ID').is_file() or directory.is_symlink():
            return False
        document = json.loads((directory / 'routes-manifest.json').read_text())
        rewrites = document['rewrites']
        if isinstance(rewrites, dict):
            rewrites = [row for values in rewrites.values() for row in values]
        from urllib.parse import urlsplit
        for row in rewrites:
            url = urlsplit(row.get('destination', ''))
            if row.get('source') == '/backend/:path*' and url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost'} and url.port == config.api_port and url.path == '/:path*' and not url.query and not url.username:
                return True
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False

def ensure_build(config, force=False):
    state = config.workspace / 'run/project-build.json'
    fingerprint = source_fingerprint(config)
    try:
        cached = json.loads(state.read_text())
        if not force and cached.get('source') == fingerprint and verify_build(config, cached['dist']):
            return cached['dist'], False
    except (OSError, ValueError, KeyError):
        pass
    prefix = config.env.get('WGS_WEB_DIST_DIR', '.next-project')
    if not re.fullmatch(r'\.[A-Za-z0-9_-]+', prefix):
        raise RuntimeFailure('INVALID_BUILD_DIRECTORY')
    dist = prefix + '-' + str(time.time_ns())
    env = {**config.env, 'WGS_WEB_DIST_DIR': dist}
    run_checked(config, [str(config.web / 'node_modules/.bin/next'), 'build', str(config.web)],
                'web-build', timeout=480, env=env, cwd=config.web)
    if source_fingerprint(config) != fingerprint or not verify_build(config, dist):
        raise RuntimeFailure('BUILD_CHANGED_OR_PROXY_MISMATCH')
    atomic_json(state, {'source': fingerprint, 'dist': dist}, config)
    return dist, True

def managed_search(config, action):
    if not config.managed_search:
        return 'external'
    config.require_privilege('elasticsearch')
    run_checked(config, [str(config.python), str(config.root / 'scripts/manage_elasticsearch.py'), action],
                'elasticsearch-' + action, timeout=360, as_user=False)
    if action == 'start':
        directory = config.workspace / 'elasticsearch'
        password = directory / 'client-password'
        if directory.is_symlink() or password.is_symlink():
            raise RuntimeFailure('INVALID_SEARCH_CREDENTIAL_PATH')
        # Applications need their own client credential, never the admin credential or Docker socket.
        os.chown(directory, config.uid, config.gid)
        os.chmod(directory, 0o750)
        os.chown(password, config.uid, config.gid)
        os.chmod(password, 0o600)
        config.env.update(WGS_ELASTICSEARCH_USERNAME='wgs-platform',
            WGS_ELASTICSEARCH_PASSWORD_FILE=str(password), WGS_ELASTICSEARCH_API_KEY='')
        # Administrative setup must not reintroduce root-owned files into the project.
        repair_project_ownership(config, directory)
    return action + 'ed'

def repair_project_ownership(config, scope=None):
    if os.geteuid() != 0:
        raise RuntimeFailure('ADMIN_REQUIRED')
    import importlib.util
    helper_path = Path(__file__).with_name('project_ownership.py')
    spec = importlib.util.spec_from_file_location('wgs_project_ownership', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    target = config.root if scope is None else Path(scope)
    if target.is_symlink() or not target.resolve().is_relative_to(config.root):
        raise RuntimeFailure('UNSAFE_PROJECT_OWNERSHIP_SCOPE')
    try:
        result = helper.repair_tree(target, config.uid, config.gid)
    except helper.OwnershipFailure as exc:
        raise RuntimeFailure(str(exc))
    result.update(project_user=config.user, uid=config.uid, gid=config.gid)
    if scope is None:
        atomic_json(config.workspace / 'run' / f'project-ownership-repair-{time.time_ns()}.json', result, config)
    return result

def application_data_roots(config):
    specifications = [
        ('WGS_SAMPLE_REGISTRY_DIR', 'sample-registry'), ('WGS_RESULTS_DIR', 'results'),
        ('WGS_UPLOAD_ROOT', 'uploads'), ('WGS_UPLOAD_JOB_ROOT', 'upload-jobs'),
        ('WGS_AGENT_CONFIG_DIR', 'agent-config'), ('WGS_AGENT_AUDIT_DIR', 'agent-audit'),
        ('', 'db'), ('', 'run'), ('', 'sessions'), ('', 'fmt'), ('WGS_BIOINFORMATICS_OUTPUT_ROOT', 'bioinformatics')]
    roots = []
    for key, default in specifications:
        configured = config.env.get(key) if key else None
        path = Path(configured) if configured else config.workspace / default
        path = path if path.is_absolute() else config.root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(config.workspace) or resolved == config.workspace or resolved.is_relative_to(config.workspace / 'elasticsearch'):
            raise RuntimeFailure('UNSAFE_APPLICATION_DATA_DIRECTORY')
        if path not in roots:
            roots.append(path)
    return roots

def prepare_application_data(config):
    """Adopt legacy application data by metadata only; never read or replace its contents."""
    changes = []
    counts = {'updated_directories': 0, 'updated_files': 0, 'skipped_symlinks': 0}
    def adopt(path, parent_fd=None, name=None):
        try:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False) if parent_fd is not None else path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            counts['skipped_symlinks'] += 1
            return
        directory = stat.S_ISDIR(info.st_mode)
        if not directory and not stat.S_ISREG(info.st_mode):
            return
        needed = 0o700 if directory else 0o600
        needs_change = info.st_uid != config.uid or stat.S_IMODE(info.st_mode) & needed != needed
        if needs_change and os.geteuid() != 0:
            raise RuntimeFailure('APPLICATION_DATA_ADMIN_REPAIR_REQUIRED')
        if needs_change and not directory and info.st_nlink > 1:
            raise RuntimeFailure('APPLICATION_DATA_HARDLINK_REQUIRES_REVIEW')
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_DIRECTORY if directory else 0)
        try:
            fd = os.open(name, flags, dir_fd=parent_fd) if parent_fd is not None else os.open(path, flags)
        except PermissionError:
            raise RuntimeFailure('APPLICATION_DATA_ADMIN_REPAIR_REQUIRED')
        try:
            current = os.fstat(fd)
            if current.st_ino != info.st_ino or current.st_dev != info.st_dev:
                raise RuntimeFailure('APPLICATION_DATA_CHANGED_DURING_REPAIR')
            if needs_change:
                changes.append({'path': str(path.relative_to(config.workspace)), 'uid': current.st_uid,
                                'gid': current.st_gid, 'mode': stat.S_IMODE(current.st_mode)})
                os.fchown(fd, config.uid, config.gid)
                mode = 0o700 if directory else 0o600 | (stat.S_IMODE(current.st_mode) & 0o100)
                os.fchmod(fd, mode)
                counts['updated_directories' if directory else 'updated_files'] += 1
            if directory:
                for entry in os.listdir(fd):
                    adopt(path / entry, fd, entry)
        finally:
            os.close(fd)
    for path in application_data_roots(config):
        adopt(path)
    if changes:
        atomic_json(config.workspace / 'run' / f'permission-migration-{time.time_ns()}.json', {'changes': changes}, config)
    return counts

def check_data_endpoints(config, role):
    port = config.api_port if role == 'workspace-api' else config.web_port
    prefix = '' if role == 'workspace-api' else '/backend'
    for path, key in [('/api/samples?limit=1', 'samples'), ('/api/reports', 'reports')]:
        try:
            data = read_json(f'http://127.0.0.1:{port}{prefix}{path}')
        except (OSError, ValueError):
            raise RuntimeFailure('DATA_ENDPOINT_FAILED_' + role.upper().replace('-', '_'))
        if not isinstance(data, dict) or not isinstance(data.get(key), list):
            raise RuntimeFailure('DATA_ENDPOINT_CONTRACT_' + role.upper().replace('-', '_'))

def read_json(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)

def wait_ready(config, role, proc, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeFailure('SERVICE_EXITED_' + role.upper().replace('-', '_'))
        try:
            if role == 'agent-daemon':
                import socket
                with socket.create_connection(('127.0.0.1', config.agent_port), timeout=1):
                    return
            port = config.api_port if role == 'workspace-api' else config.web_port
            prefix = '' if role == 'workspace-api' else '/backend'
            data = read_json(f'http://127.0.0.1:{port}{prefix}/api/knowledge-base/config')
            expected = config.env.get('WGS_CLAIM_API_KNOWLEDGE_BASE_ID')
            if expected and data.get('knowledge_base_id') != int(expected):
                raise RuntimeFailure('WRONG_KNOWLEDGE_BASE')
            check_data_endpoints(config, role)
            if role == 'workspace-web':
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                    if response.status != 200:
                        continue
            return
        except (OSError, ValueError):
            time.sleep(0.2)
    raise RuntimeFailure('READINESS_TIMEOUT_' + role.upper().replace('-', '_'))

def start_process(config, role, dist):
    env = dict(config.env)
    if role == 'workspace-api':
        args = [str(config.python), '-m', 'uvicorn', 'app.main:app', '--app-dir', str(config.root / 'apps/workspace-api'), '--host', '127.0.0.1', '--port', str(config.api_port)]
        cwd = config.root
    elif role == 'workspace-web':
        env['WGS_WEB_DIST_DIR'] = dist
        args = [str(config.web / 'node_modules/.bin/next'), 'start', str(config.web), '-p', str(config.web_port), '-H', env['WGS_WEB_HOST']]
        cwd = config.web
    else:
        args = [str(config.python.parent / 'wgs-agent'), 'serve', '--host', '127.0.0.1', '--port', str(config.agent_port)]
        cwd = config.root
    path = log_path(config, role)
    with path.open('ab') as handle:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=handle, stderr=handle,
            start_new_session=True, preexec_fn=config.drop_privilege if os.geteuid() == 0 else None)
    # Record ownership immediately, including starts that later fail readiness.
    record = proc_record(proc.pid)
    if not record:
        raise RuntimeFailure('SERVICE_START_FAILED')
    pidfile = config.workspace / 'run' / (role + '.pid')
    atomic_json(pidfile, proc.pid, config)
    statepath = config.workspace / 'run/project-processes.json'
    try:
        state = json.loads(statepath.read_text())
    except (OSError, ValueError):
        state = {'project': str(config.root), 'services': {}}
    state['services'][role] = {k: record[k] for k in ('pid', 'start', 'pgid', 'uid')}
    atomic_json(statepath, state, config)
    wait_ready(config, role, proc)
    return proc.pid

def status(config):
    found = discover(config.root)
    result = {}
    for role in ROLES:
        pids = sorted(r['pid'] for r in found.values() if r['role'] == role)
        result[role] = {'pids': pids, 'state': 'running' if pids else 'disabled' if role == 'agent-daemon' and not config.agent_enabled else 'stopped'}
        if pids and role in {'workspace-api', 'workspace-web'}:
            try:
                check_data_endpoints(config, role)
                result[role]['data_ready'] = True
            except RuntimeFailure as exc:
                result[role].update(state='degraded', data_ready=False, error=exc.code)
    result['ports'] = {'web': config.web_port, 'api': config.api_port, 'agent': config.agent_port}
    if config.managed_search:
        if os.geteuid() != 0:
            result['elasticsearch'] = search_health(config)
        else:
            name = 'wgs_managed_search_runtime'
            spec = importlib.util.spec_from_file_location(name, config.root / 'scripts/manage_elasticsearch.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            previous = dict(os.environ)
            try:
                os.environ.update(config.env)
                # Recreate after setting the resolved workspace.
                instance = module.ManagedElasticsearch()
                container = instance._inspect('container', instance.name)
                if container:
                    instance._owned(container)
                result['elasticsearch'] = {'state': 'running' if container and container.get('State', {}).get('Running') else 'stopped'}
            except Exception:
                result['elasticsearch'] = {'state': 'unavailable'}
            finally:
                os.environ.clear(); os.environ.update(previous)
    else:
        result['elasticsearch'] = {'state': 'external'}
    return result

def search_health(config):
    """Read-only status with the application credential; no Docker/admin access needed."""
    import base64
    from urllib.parse import urlsplit
    url = config.env['WGS_ELASTICSEARCH_URL'].rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.username or parsed.query or parsed.path:
        return {'state': 'invalid_configuration'}
    try:
        password = (config.workspace / 'elasticsearch/client-password').read_text().strip()
        authorization = base64.b64encode(('wgs-platform:' + password).encode()).decode()
        request = urllib.request.Request(url + '/_cluster/health', headers={'Authorization': 'Basic ' + authorization})
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.load(response)
        health = data.get('status')
        return {'state': 'running' if health in {'green', 'yellow'} else 'unhealthy',
                'health': health if health in {'green', 'yellow', 'red'} else 'unknown'}
    except PermissionError:
        return {'state': 'requires_admin'}
    except (OSError, ValueError):
        return {'state': 'unavailable'}

def start(config, component='all', force_build=False):
    config.require_privilege(component)
    if component in {'all', 'elasticsearch'} and config.managed_search:
        managed_search(config, 'status')
    roles = ROLES if component == 'all' else (component,)
    if discover(config.root, roles):
        raise RuntimeFailure('PROJECT_ALREADY_RUNNING_USE_RESTART')
    if 'workspace-api' in roles:
        if os.geteuid() == 0:
            repair_project_ownership(config)
        else:
            prepare_application_data(config)
    dist, rebuilt = (ensure_build(config, force_build) if 'workspace-web' in roles else ('', False))
    dependency_started = False
    started = {}
    try:
        if component in {'all', 'elasticsearch'}:
            managed_search(config, 'start')
            dependency_started = config.managed_search
        if component == 'elasticsearch':
            return {'elasticsearch': 'running'}
        if component == 'all':
            run_checked(config, [str(config.python), str(config.root / 'scripts/init_data.py')], 'initialize', timeout=120)
            if config.managed_search:
                run_checked(config, [str(config.python), '-c', 'from wgs_fmt_platform.infrastructure.search import HybridKnowledgeSearch; HybridKnowledgeSearch().ensure_index()'], 'search-index', timeout=60)
        for role in roles:
            if role == 'agent-daemon' and not config.agent_enabled:
                continue
            started[role] = start_process(config, role, dist)
        return {'services': started, 'build_rebuilt': rebuilt, 'ports': {'web': config.web_port, 'api': config.api_port}}
    except BaseException:
        stop_processes(config, roles)
        if dependency_started:
            managed_search(config, 'stop')
        raise

def stop(config, component='all'):
    config.require_privilege(component)
    if component in {'all', 'elasticsearch'} and config.managed_search:
        managed_search(config, 'status')
    roles = ROLES if component == 'all' else () if component == 'elasticsearch' else (component,)
    count = stop_processes(config, roles) if roles else 0
    dependency = managed_search(config, 'stop') if component in {'all', 'elasticsearch'} else 'unchanged'
    return {'stopped_process_count': count, 'project_process_count': len(discover(config.root, roles)) if roles else 0, 'elasticsearch': dependency}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'reload', 'status', 'build', 'preflight', 'repair-data', 'repair-ownership'])
    parser.add_argument('--component', choices=['all', *ROLES, 'elasticsearch'], default='all')
    parser.add_argument('--force-build', action='store_true')
    parser.add_argument('--json', action='store_true', help='Retained for scripting; output is always a safe JSON summary')
    args = parser.parse_args(argv)
    try:
        config = Config.load()
        if args.action == 'status':
            result = status(config)
        elif args.action == 'preflight':
            config.require_privilege(args.component)
            result = {'ready': True}
        else:
            if args.action in {'repair-data', 'repair-ownership'} and os.geteuid() != 0:
                raise RuntimeFailure('ADMIN_REQUIRED')
            if args.action not in {'build', 'repair-data', 'repair-ownership'}:
                config.require_privilege(args.component)
            with deployment_lock(config):
                if args.action == 'repair-ownership':
                    result = repair_project_ownership(config)
                elif args.action == 'repair-data':
                    result = prepare_application_data(config)
                elif args.action == 'build':
                    _, rebuilt = ensure_build(config, args.force_build)
                    result = {'build_ready': True, 'build_rebuilt': rebuilt}
                elif args.action == 'stop':
                    result = stop(config, args.component)
                else:
                    if args.action in {'restart', 'reload'}:
                        stop(config, args.component)
                        # Reload after shutdown: never carry a stale .env selection into the new instances.
                        config = Config.load()
                    result = start(config, args.component, args.force_build)
        print(json.dumps({'ok': True, 'action': args.action, 'component': args.component, 'result': result}))
        return 0
    except RuntimeFailure as exc:
        print(json.dumps({'ok': False, 'error': exc.code}))
        return 77 if exc.code == 'ADMIN_REQUIRED' else 1
    except Exception:
        print(json.dumps({'ok': False, 'error': 'RUNTIME_OPERATION_FAILED'}))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
