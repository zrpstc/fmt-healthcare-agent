#!/usr/bin/env python3
"""Manage one authenticated, loopback-only Elasticsearch container per workspace.

Uses only the standard library so stop/status also work without the application
environment. Never removes containers or volumes, or changes host settings.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
LABEL = "io.wgs-fmt.elasticsearch.workspace"
CONFIG_LABEL = "io.wgs-fmt.elasticsearch.config"
APP_USER = "wgs-platform"
DEFAULT_VERSION = "8.19.23"


class ManagedElasticsearchError(RuntimeError):
    pass


def private_write(path: Path, content: str) -> None:
    """Atomically replace a secret without making it world-readable."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class ManagedElasticsearch:
    def __init__(self) -> None:
        workspace = Path(os.environ.get("WGS_WORKSPACE") or ROOT / "var").expanduser()
        self.workspace = (ROOT / workspace).resolve()
        if self.workspace in {Path("/"), Path.home().resolve(), ROOT}:
            raise ManagedElasticsearchError("WGS_WORKSPACE must be a dedicated data directory")
        self.directory = self.workspace / "elasticsearch"
        suffix = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:12]
        self.name = f"wgs-elasticsearch-{suffix}"
        self.volume = f"{self.name}-data"
        # Explicitly use a local socket, never an inherited remote Docker context.
        docker_socket = os.environ.get("WGS_ELASTICSEARCH_DOCKER_SOCKET", "/var/run/docker.sock")
        if not Path(docker_socket).is_absolute():
            raise ManagedElasticsearchError("WGS_ELASTICSEARCH_DOCKER_SOCKET must be absolute")
        self.docker = ["docker", "--host", f"unix://{docker_socket}"]
        self.opener = build_opener(ProxyHandler({}))

    def _docker(self, *arguments: str, missing_ok: bool = False, timeout: int = 30):
        try:
            result = subprocess.run(
                [*self.docker, *arguments], capture_output=True, text=True, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagedElasticsearchError("Docker is unavailable or the command timed out") from exc
        if result.returncode:
            if missing_ok and any(
                text in result.stderr.lower()
                for text in ("no such container", "no such volume", "no such image", "no such object")
            ):
                return None
            # Commands contain paths/configuration, never passwords. Avoid dumping
            # inspect output or subprocess arguments that might include secrets.
            raise ManagedElasticsearchError(
                "Docker command failed; check the local Docker socket permissions and daemon. "
                + result.stderr.strip()
            )
        return result.stdout.strip()

    def _inspect(self, kind: str, name: str):
        result = self._docker(kind, "inspect", name, missing_ok=True)
        return json.loads(result)[0] if result is not None else None

    def _owned(self, resource: dict, *, volume: bool = False) -> None:
        labels = resource.get("Labels") if volume else resource.get("Config", {}).get("Labels")
        if (labels or {}).get(LABEL) != str(self.workspace):
            raise ManagedElasticsearchError("Resource ownership differs; refusing to manage it")

    def _configure(self) -> None:
        parsed = urlsplit(os.environ.get("WGS_ELASTICSEARCH_URL", "http://127.0.0.1:9200"))
        if (
            parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        ):
            raise ManagedElasticsearchError(
                "Managed Elasticsearch requires http://127.0.0.1:<port>; "
                "set WGS_ELASTICSEARCH_MANAGED=false to use an external instance"
            )
        self.port = parsed.port if parsed.port is not None else 9200
        if not 1 <= self.port <= 65535:
            raise ManagedElasticsearchError("Invalid Elasticsearch port")
        if self.port in {
            int(os.environ.get(name, default))
            for name, default in (("WGS_WEB_PORT", "8502"), ("WGS_API_PORT", "8503"), ("WGS_PORT", "7438"))
        }:
            raise ManagedElasticsearchError("Elasticsearch port conflicts with another project service")
        version = os.environ.get("WGS_ELASTICSEARCH_VERSION", DEFAULT_VERSION)
        if not re.fullmatch(r"8\.\d+\.\d+", version):
            raise ManagedElasticsearchError("WGS_ELASTICSEARCH_VERSION must be a pinned 8.x.y version")
        self.image = f"docker.elastic.co/elasticsearch/elasticsearch:{version}"
        self.memory = os.environ.get("WGS_ELASTICSEARCH_MEMORY", "2g")
        self.heap = os.environ.get("WGS_ELASTICSEARCH_HEAP", "512m")
        sizes = []
        for size in (self.memory, self.heap):
            if not re.fullmatch(r"[1-9][0-9]*[mg]", size):
                raise ManagedElasticsearchError("Elasticsearch memory/heap must use m or g units")
            sizes.append(int(size[:-1]) * (1024 if size[-1] == "g" else 1))
        if sizes[0] < 1024 or sizes[1] < 256 or sizes[1] * 2 > sizes[0]:
            raise ManagedElasticsearchError("Use memory >= 1g, heap >= 256m and heap <= half of memory")
        self.timeout = int(os.environ.get("WGS_ELASTICSEARCH_START_TIMEOUT", "120"))
        if not 1 <= self.timeout <= 600:
            raise ManagedElasticsearchError("Elasticsearch startup timeout must be 1..600 seconds")
        self.index = os.environ.get("WGS_ELASTICSEARCH_INDEX", "wgs-knowledge")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", self.index)
            or self.index in {".", ".."} or len(self.index.encode()) > 255
        ):
            raise ManagedElasticsearchError("Use one explicit, lowercase Elasticsearch index name")
        self.url = f"http://127.0.0.1:{self.port}"
        self.fingerprint = hashlib.sha256(
            json.dumps([self.image, self.port, self.memory, self.heap]).encode()
        ).hexdigest()

    def _password(self, name: str, *, create: bool) -> str:
        path = self.directory / name
        if not path.exists():
            if not create:
                raise ManagedElasticsearchError(f"Missing {name}; restore credentials before reusing the data")
            private_write(path, secrets.token_urlsafe(32) + "\n")
        os.chmod(path, 0o600)
        password = path.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", password):
            raise ManagedElasticsearchError(f"Invalid credential file: {path}")
        return password

    def _request(self, method: str, path: str, password: str, payload=None):
        authorization = base64.b64encode(f"elastic:{password}".encode()).decode()
        request = Request(
            self.url + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Basic {authorization}", "Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=3) as response:
            return json.load(response)

    def _wait_ready(self, password: str) -> None:
        deadline = time.monotonic() + self.timeout
        last_auth_status = None
        while time.monotonic() < deadline:
            try:
                health = self._request("GET", "/_cluster/health?wait_for_status=yellow&timeout=1s", password)
                last_auth_status = None
                if health.get("cluster_name") != self.name:
                    raise ManagedElasticsearchError("Unexpected cluster at the configured local port")
                if health.get("status") in {"yellow", "green"} and not health.get("timed_out"):
                    return
            except HTTPError as exc:
                # HTTP can listen before persisted security state is ready.
                # A single early 401/403 must not abort and stop a valid node.
                last_auth_status = exc.code if exc.code in {401, 403} else None
            except (URLError, TimeoutError, OSError, ValueError):
                last_auth_status = None
            container = self._inspect("container", self.name)
            if not container or not container["State"]["Running"]:
                raise ManagedElasticsearchError(f"Elasticsearch exited; inspect docker logs {self.name}")
            time.sleep(1)
        if last_auth_status is not None:
            raise ManagedElasticsearchError(
                "Elasticsearch rejected the saved credentials after the startup wait "
                f"({self.timeout}s, HTTP {last_auth_status}); verify the existing credentials. "
                "The data volume and saved passwords have not been reset."
            )
        raise ManagedElasticsearchError(f"Elasticsearch startup timed out; inspect docker logs {self.name}")

    def start(self) -> None:
        self._configure()
        self._docker("version", "--format", "{{.Server.Version}}")
        container = self._inspect("container", self.name)
        volume = self._inspect("volume", self.volume)
        if container:
            self._owned(container)
            binding = container.get("HostConfig", {}).get("PortBindings", {}).get("9200/tcp")
            if (
                container["Config"]["Labels"].get(CONFIG_LABEL) != self.fingerprint
                or binding != [{"HostIp": "127.0.0.1", "HostPort": str(self.port)}]
            ):
                raise ManagedElasticsearchError(
                    "Existing container configuration differs; restore its settings or recreate "
                    "only the stopped container, keeping its data volume and credentials"
                )
            if not volume or not any(
                mount.get("Type") == "volume" and mount.get("Name") == self.volume
                and mount.get("Destination") == "/usr/share/elasticsearch/data"
                for mount in container.get("Mounts", [])
            ):
                raise ManagedElasticsearchError("Existing container data volume differs or is missing")
        if volume:
            self._owned(volume, volume=True)
        if not container:
            # Avoid creating credentials/volumes or downloading an image when a
            # separately managed local service already owns the requested port.
            try:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", self.port))
            except OSError as exc:
                raise ManagedElasticsearchError(
                    f"Local port {self.port} is unavailable; choose another port or set "
                    "WGS_ELASTICSEARCH_MANAGED=false to use the existing service"
                ) from exc
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        password = self._password("password", create=not container and not volume)
        client_password = self._password("client-password", create=True)
        if not volume:
            self._docker("volume", "create", "--label", f"{LABEL}={self.workspace}", self.volume)
        started_here = False
        try:
            if not container:
                # Pull only the official, explicitly versioned image when absent.
                if self._inspect("image", self.image) is None:
                    print(f"Pulling {self.image}", flush=True)
                    self._docker("image", "pull", self.image, timeout=600)
                env_file = self.directory / "docker.env"
                private_write(env_file, f"ELASTIC_PASSWORD={password}\n")
                try:
                    self._docker(
                        "container", "run", "--detach", "--name", self.name,
                        "--label", f"{LABEL}={self.workspace}",
                        "--label", f"{CONFIG_LABEL}={self.fingerprint}",
                        "--publish", f"127.0.0.1:{self.port}:9200",
                        "--mount", f"type=volume,src={self.volume},dst=/usr/share/elasticsearch/data",
                        "--memory", self.memory, "--restart", "no",
                        "--log-driver", "local", "--log-opt", "max-size=10m", "--log-opt", "max-file=3",
                        "--env-file", str(env_file),
                        "--env", "discovery.type=single-node", "--env", f"cluster.name={self.name}",
                        "--env", "xpack.security.enabled=true",
                        "--env", "xpack.security.autoconfiguration.enabled=false",
                        "--env", "xpack.security.http.ssl.enabled=false",
                        "--env", "xpack.security.transport.ssl.enabled=false",
                        "--env", "node.store.allow_mmap=false", "--env", "xpack.ml.enabled=false",
                        "--env", f"ES_JAVA_OPTS=-Xms{self.heap} -Xmx{self.heap}", self.image,
                    )
                finally:
                    env_file.unlink(missing_ok=True)
                started_here = True
            elif not container["State"]["Running"]:
                self._docker("container", "start", self.name)
                started_here = True
            print(f"Waiting for Elasticsearch: {self.url}", flush=True)
            self._wait_ready(password)
            # The application receives an index-scoped account, not the bootstrap password.
            self._request("PUT", "/_security/role/wgs-platform", password, {
                "cluster": ["monitor"],
                "indices": [{"names": [self.index], "privileges": ["create_index", "index", "read", "view_index_metadata"]}],
            })
            self._request("PUT", f"/_security/user/{APP_USER}", password, {
                "password": client_password, "roles": ["wgs-platform"],
            })
        except Exception:
            if started_here:
                self._docker("container", "stop", "--time", "30", self.name, timeout=40)
            raise
        print(f"Elasticsearch ready: {self.url} (authenticated, container {self.name})")

    def stop(self) -> None:
        if not self.directory.exists():
            print("elasticsearch not managed in this workspace")
            return
        container = self._inspect("container", self.name)
        if container:
            self._owned(container)
            if container["State"]["Running"]:
                self._docker("container", "stop", "--time", "30", self.name, timeout=40)
        print("elasticsearch stopped; container, credentials and data volume preserved")

    def status(self) -> None:
        if not self.directory.exists():
            print("elasticsearch not managed in this workspace")
            return
        container = self._inspect("container", self.name)
        if container:
            self._owned(container)
        state = container["State"]["Status"] if container else "not created"
        print(f"elasticsearch {state}: {self.name}; data volume: {self.volume}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    arguments = parser.parse_args()
    try:
        getattr(ManagedElasticsearch(), arguments.action)()
    except (ManagedElasticsearchError, OSError, ValueError) as exc:
        # Do not print HTTP response bodies or request headers containing credentials.
        message = f"Elasticsearch HTTP request failed ({exc.code})" if isinstance(exc, HTTPError) else str(exc)
        print(f"elasticsearch: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
