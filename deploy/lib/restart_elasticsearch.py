#!/usr/bin/env python3
"""Restart the Elasticsearch this project uses and wait until it is healthy.

Application processes are left alone.  Managed mode restarts the project's own
container through runtime.py.  External mode restarts the local Docker container
that publishes the port of WGS_ELASTICSEARCH_URL: found automatically, or named
with --container, which must publish that same port.  Exit code 77 asks the shell
wrapper to retry with sudo when the Docker socket is not accessible.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime  # noqa: E402
from runtime import RuntimeFailure  # noqa: E402

LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def docker_command(config):
    socket_path = config.env.get('WGS_ELASTICSEARCH_DOCKER_SOCKET') or '/var/run/docker.sock'
    if not Path(socket_path).is_absolute():
        raise RuntimeFailure('INVALID_ELASTICSEARCH_DOCKER_SOCKET')
    if os.geteuid() != 0 and not os.access(socket_path, os.R_OK | os.W_OK):
        raise RuntimeFailure('ADMIN_REQUIRED')

    def docker(*arguments, timeout=60):
        try:
            # Explicit local socket, never an inherited remote Docker context.
            result = subprocess.run(['docker', '--host', 'unix://' + socket_path, *arguments], capture_output=True,
                                    text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeFailure('ELASTICSEARCH_DOCKER_UNAVAILABLE')
        if result.returncode:
            raise RuntimeFailure('ELASTICSEARCH_DOCKER_FAILED')
        return result.stdout
    return docker


def search_port(config):
    parsed = urlsplit(config.env['WGS_ELASTICSEARCH_URL'])
    if parsed.hostname not in LOCAL_HOSTS:
        raise RuntimeFailure('ELASTICSEARCH_NOT_ON_THIS_HOST')
    return str(parsed.port or 9200)


def publishes(container, port):
    bindings = (container.get('HostConfig') or {}).get('PortBindings') or {}
    return any(str(b.get('HostPort')) == port for values in bindings.values() for b in values or [])


def find_container(docker, port, name=None):
    """Return (name, running) of the one container publishing ``port`` (stopped ones included)."""
    names = [name] if name else docker('container', 'ls', '--all', '--format', '{{.Names}}').split()
    if not names:
        raise RuntimeFailure('ELASTICSEARCH_CONTAINER_NOT_FOUND')
    try:
        containers = json.loads(docker('container', 'inspect', *names))
    except RuntimeFailure:
        if name:
            raise RuntimeFailure('ELASTICSEARCH_CONTAINER_NOT_FOUND')
        raise
    matches = [c for c in containers if publishes(c, port)]
    if name and not matches:
        raise RuntimeFailure('ELASTICSEARCH_CONTAINER_PORT_MISMATCH')
    if not matches:
        raise RuntimeFailure('ELASTICSEARCH_CONTAINER_NOT_FOUND')
    if len(matches) > 1:
        raise RuntimeFailure('ELASTICSEARCH_CONTAINER_AMBIGUOUS')
    found = matches[0]
    return found['Name'].lstrip('/'), bool((found.get('State') or {}).get('Running'))


def wait_healthy(config, timeout, health=None):
    health = health or runtime.search_health
    deadline = time.monotonic() + timeout
    while True:
        state = health(config)
        if state['state'] == 'running':
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(2)


def restart(config, *, container=None, timeout=None, docker=None, health=None):
    port = search_port(config)
    docker = docker or docker_command(config)
    name, running = find_container(docker, port, container)
    if running:
        docker('container', 'restart', '--time', '30', name, timeout=90)
    else:
        docker('container', 'start', name, timeout=90)
    state = wait_healthy(config, timeout, health)
    result = {'container': name, 'action': 'restarted' if running else 'started', 'elasticsearch': state}
    if state['state'] != 'running':
        result['error'] = 'ELASTICSEARCH_UNHEALTHY_AFTER_RESTART'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--container', help='container name; default: the one publishing the configured port')
    parser.add_argument('--timeout', type=int, help='seconds to wait for green/yellow (default WGS_ELASTICSEARCH_START_TIMEOUT or 120)')
    args = parser.parse_args(argv)
    try:
        config = runtime.Config.load()
        if config.managed_search:
            # The project's own container: same lifecycle as `restart --component elasticsearch`.
            return runtime.main(['restart', '--component', 'elasticsearch'])
        timeout = args.timeout or int(config.env.get('WGS_ELASTICSEARCH_START_TIMEOUT') or 120)
        if not 1 <= timeout <= 600:
            raise RuntimeFailure('INVALID_ELASTICSEARCH_TIMEOUT')
        if args.container is not None and (not args.container or args.container.startswith('-')):
            raise RuntimeFailure('INVALID_ELASTICSEARCH_CONTAINER')
        result = restart(config, container=args.container, timeout=timeout)
    except RuntimeFailure as exc:
        print(json.dumps({'ok': False, 'error': exc.code}))
        return 77 if exc.code == 'ADMIN_REQUIRED' else 1
    except ValueError:
        print(json.dumps({'ok': False, 'error': 'INVALID_ELASTICSEARCH_TIMEOUT'}))
        return 1
    ok = 'error' not in result
    print(json.dumps({'ok': ok, 'action': 'restart-elasticsearch', 'result': result}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
