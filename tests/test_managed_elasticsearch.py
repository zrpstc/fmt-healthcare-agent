"""Lifecycle regression tests; no Docker daemon or application packages required."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("managed_elasticsearch", ROOT / "scripts/manage_elasticsearch.py")
managed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(managed)


class DockerDouble:
    def __init__(self, manager):
        self.manager = manager
        self.container = None
        self.volume = None
        self.commands = []
        self.image = {"Id": "test-image"}

    def __call__(self, *args, **kwargs):
        self.commands.append(args)
        if args[1] == "inspect":
            resource = {"container": self.container, "volume": self.volume, "image": self.image}[args[0]]
            return json.dumps([resource]) if resource else None
        if args[:2] == ("volume", "create"):
            self.volume = {"Labels": {managed.LABEL: str(self.manager.workspace)}}
        if args[:2] == ("container", "run"):
            self.container = {
                "Config": {"Labels": {
                    managed.LABEL: str(self.manager.workspace),
                    managed.CONFIG_LABEL: self.manager.fingerprint,
                }},
                "HostConfig": {"PortBindings": {"9200/tcp": [{
                    "HostIp": "127.0.0.1", "HostPort": str(self.manager.port),
                }]}},
                "Mounts": [{"Type": "volume", "Name": self.manager.volume,
                            "Destination": "/usr/share/elasticsearch/data"}],
                "State": {"Running": True, "Status": "running"},
            }
        if args[:2] in {("container", "start"), ("container", "stop")}:
            running = args[1] == "start"
            self.container["State"] = {"Running": running, "Status": "running" if running else "exited"}
        return "test-id"


class ManagedElasticsearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {"WGS_WORKSPACE": self.temporary.name}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.manager = managed.ManagedElasticsearch()
        self.docker = DockerDouble(self.manager)
        self.manager._docker = self.docker
        self.requests = []
        self.manager._request = self.request
        self.probe = patch.object(managed.socket, "socket")
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def request(self, method, path, password, payload=None):
        self.requests.append((method, path, payload))
        return {"cluster_name": self.manager.name, "status": "yellow", "timed_out": False}

    def test_fresh_start_uses_private_credentials_and_persistent_loopback_node(self):
        self.manager.start()
        run = next(command for command in self.docker.commands if command[:2] == ("container", "run"))
        self.assertIn("127.0.0.1:9200:9200", run)
        self.assertIn("xpack.security.enabled=true", run)
        self.assertIn("node.store.allow_mmap=false", run)
        self.assertIn("2g", run)
        self.assertIn("ES_JAVA_OPTS=-Xms512m -Xmx512m", run)
        self.assertTrue(run[-1].startswith("docker.elastic.co/elasticsearch/elasticsearch:8."))
        for name in ("password", "client-password"):
            credential = self.manager.directory / name
            self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(credential.read_text().strip(), self.output.getvalue() + repr(run))
        self.assertEqual(self.manager.directory.stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.manager.directory / "docker.env").exists())
        role = next(payload for _, path, payload in self.requests if "/role/" in path)
        self.assertEqual(role["indices"][0]["names"], ["wgs-knowledge"])
        self.assertNotIn("all", role["cluster"])

    def test_restart_is_idempotent_and_stop_preserves_data_and_credentials(self):
        self.manager.start()
        before = (self.manager.directory / "password").read_bytes()
        self.manager.start()
        self.manager.stop()
        self.assertIsNotNone(self.docker.volume)
        self.assertFalse(self.docker.container["State"]["Running"])
        self.manager.start()
        self.assertEqual((self.manager.directory / "password").read_bytes(), before)
        self.assertEqual(sum(command[:2] == ("container", "run") for command in self.docker.commands), 1)
        self.assertEqual(sum(command[:2] == ("container", "start") for command in self.docker.commands), 1)
        self.assertFalse(any("rm" in command for command in self.docker.commands))

    def test_foreign_volume_or_container_is_never_adopted_or_stopped(self):
        self.docker.volume = {"Labels": {managed.LABEL: "/another-workspace"}}
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "ownership"):
            self.manager.start()
        self.docker.volume = None
        self.manager.start()
        self.docker.container["Config"]["Labels"][managed.LABEL] = "/another-workspace"
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "ownership"):
            self.manager.stop()
        self.assertTrue(self.docker.container["State"]["Running"])

    def test_reusing_data_without_bootstrap_password_fails_without_reset(self):
        self.manager.start()
        (self.manager.directory / "password").unlink()
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "restore credentials"):
            self.manager.start()
        self.assertFalse((self.manager.directory / "password").exists())

    def test_occupied_port_does_not_create_local_state_or_launch_anything(self):
        managed.socket.socket.return_value.__enter__.return_value.bind.side_effect = OSError("in use")
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "Local port 9200 is unavailable"):
            self.manager.start()
        self.assertFalse(self.manager.directory.exists())
        self.assertFalse(any(command[:2] in {("volume", "create"), ("container", "run"), ("image", "pull")}
                             for command in self.docker.commands))

    def test_unsafe_existing_binding_and_changed_configuration_are_rejected(self):
        self.manager.start()
        self.docker.container["HostConfig"]["PortBindings"]["9200/tcp"][0]["HostIp"] = "0.0.0.0"
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "configuration differs"):
            self.manager.start()
        self.docker.container["HostConfig"]["PortBindings"]["9200/tcp"][0]["HostIp"] = "127.0.0.1"
        os.environ["WGS_ELASTICSEARCH_HEAP"] = "1g"
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "configuration differs"):
            self.manager.start()

    def test_readiness_failure_stops_only_the_container_started_by_this_call(self):
        self.manager._wait_ready = Mock(side_effect=managed.ManagedElasticsearchError("timed out"))
        with self.assertRaisesRegex(managed.ManagedElasticsearchError, "timed out"):
            self.manager.start()
        self.assertFalse(self.docker.container["State"]["Running"])
        self.docker.container["State"]["Running"] = True
        self.docker.commands.clear()
        with self.assertRaises(managed.ManagedElasticsearchError):
            self.manager.start()
        self.assertFalse(any(command[:2] == ("container", "stop") for command in self.docker.commands))

    def test_readiness_timeout_retains_diagnostics_and_stops_new_node(self):
        self.manager._request = Mock(return_value={"cluster_name": self.manager.name, "status": "red"})
        with patch.object(managed.time, "monotonic", side_effect=[0, 0, 121]), patch.object(managed.time, "sleep"):
            with self.assertRaisesRegex(managed.ManagedElasticsearchError, "startup timed out"):
                self.manager.start()
        self.assertFalse(self.docker.container["State"]["Running"])
        self.assertTrue((self.manager.directory / "password").exists())

    def test_persistent_auth_failure_waits_until_deadline_without_exposing_secrets(self):
        self.manager._request = Mock(side_effect=HTTPError("local", 401, "Unauthorized", {}, None))
        with patch.object(managed.time, "monotonic", side_effect=[0, 0, 1, 121]), patch.object(managed.time, "sleep"):
            with self.assertRaisesRegex(managed.ManagedElasticsearchError, "rejected the saved credentials after the startup wait"):
                self.manager.start()
        self.assertFalse(self.docker.container["State"]["Running"])
        self.assertEqual(self.manager._request.call_count, 2)

    def test_transient_auth_failures_during_restart_do_not_stop_the_container(self):
        self.manager.start()
        self.manager.stop()
        before = (self.manager.directory / "password").read_bytes()
        self.docker.commands.clear()
        healthy = {"cluster_name": self.manager.name, "status": "yellow", "timed_out": False}
        self.manager._request = Mock(side_effect=[
            HTTPError("local", 401, "Unauthorized", {}, None),
            HTTPError("local", 403, "Forbidden", {}, None),
            healthy, {}, {},
        ])
        with patch.object(managed.time, "monotonic", side_effect=[0, 0, 1, 2]), patch.object(managed.time, "sleep"):
            self.manager.start()
        self.assertTrue(self.docker.container["State"]["Running"])
        self.assertEqual((self.manager.directory / "password").read_bytes(), before)
        self.assertEqual(self.manager._request.call_count, 5)
        self.assertFalse(any(command[:2] == ("container", "stop") for command in self.docker.commands))

    def test_valid_auth_with_unhealthy_cluster_reports_startup_timeout(self):
        self.manager.start()
        self.manager._request = Mock(side_effect=[
            HTTPError("local", 401, "Unauthorized", {}, None),
            {"cluster_name": self.manager.name, "status": "red", "timed_out": True},
        ])
        with patch.object(managed.time, "monotonic", side_effect=[0, 0, 1, 121]), patch.object(managed.time, "sleep"):
            with self.assertRaisesRegex(managed.ManagedElasticsearchError, "startup timed out"):
                self.manager._wait_ready("synthetic-password")

    def test_external_urls_invalid_resources_and_wildcard_index_fail_before_docker(self):
        cases = [
            ("WGS_ELASTICSEARCH_URL", "http://10.0.0.2:9200"),
            ("WGS_ELASTICSEARCH_URL", "http://127.0.0.1:0"),
            ("WGS_ELASTICSEARCH_URL", "http://127.0.0.1:8503"),
            ("WGS_ELASTICSEARCH_URL", "http://user:password@127.0.0.1:9200"),
            ("WGS_ELASTICSEARCH_MEMORY", "512m"),
            ("WGS_ELASTICSEARCH_HEAP", "2g"),
            ("WGS_ELASTICSEARCH_VERSION", "latest"),
            ("WGS_ELASTICSEARCH_INDEX", "*"),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                with self.assertRaises((managed.ManagedElasticsearchError, ValueError)):
                    self.manager.start()
        self.assertEqual(self.docker.commands, [])

    def test_remote_docker_context_is_not_used(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote:2375", "DOCKER_CONTEXT": "remote"}):
            manager = managed.ManagedElasticsearch()
        self.assertEqual(manager.docker, ["docker", "--host", "unix:///var/run/docker.sock"])

    def test_http_request_uses_local_basic_auth_and_json(self):
        self.manager._configure()
        self.manager.opener = Mock()
        self.manager.opener.open.return_value = io.BytesIO(b'{"created": true}')
        result = managed.ManagedElasticsearch._request(
            self.manager, "PUT", "/_security/role/wgs-platform", "synthetic-password", {"cluster": ["monitor"]},
        )
        self.assertEqual(result, {"created": True})
        request = self.manager.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9200/_security/role/wgs-platform")
        expected_auth = managed.base64.b64encode(b"elastic:synthetic-password").decode()
        self.assertEqual(request.get_header("Authorization"), f"Basic {expected_auth}")
        self.assertEqual(json.loads(request.data), {"cluster": ["monitor"]})

    def test_missing_image_is_pulled_but_docker_permission_errors_are_not_missing(self):
        self.docker.image = None
        self.manager.start()
        self.assertTrue(any(command[:2] == ("image", "pull") for command in self.docker.commands))
        manager = managed.ManagedElasticsearch()
        for message in ("Error: No such image: test", "permission denied"):
            result = subprocess.CompletedProcess([], 1, "", message)
            with patch.object(managed.subprocess, "run", return_value=result):
                if "No such image" in message:
                    self.assertIsNone(manager._inspect("image", "test"))
                else:
                    with self.assertRaisesRegex(managed.ManagedElasticsearchError, "permissions"):
                        manager._inspect("image", "test")


class StartupScriptTests(unittest.TestCase):
    """Exercise real shell ordering with local command doubles, no listening services."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "deploy", self.root / "deploy")
        python = self.root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('''#!/usr/bin/env bash
case "$1" in
  */manage_elasticsearch.py)
    echo "elastic:$2" >> "$WGS_WORKSPACE/events"
    if [[ "$2" == start ]]; then
      [[ "${FAIL_ELASTIC:-0}" == 0 ]] || exit 1
      mkdir -p "$WGS_WORKSPACE/elasticsearch"
      printf 'test-password' > "$WGS_WORKSPACE/elasticsearch/client-password"
    fi ;;
  */init_data.py) mkdir -p "$WGS_WORKSPACE/run" "$WGS_WORKSPACE/logs" ;;
  -c)
    [[ -f "$WGS_ELASTICSEARCH_PASSWORD_FILE" && "$WGS_ELASTICSEARCH_USERNAME" == wgs-platform && -z "$WGS_ELASTICSEARCH_API_KEY" ]] || exit 2
    echo "index" >> "$WGS_WORKSPACE/events" ;;
esac
''')
        python.chmod(0o700)
        web = self.root / "apps/workspace-web"
        (web / "node_modules/.bin").mkdir(parents=True)
        (web / ".next").mkdir()
        (web / ".next/BUILD_ID").touch()
        next_binary = web / "node_modules/.bin/next"
        next_binary.write_text("#!/usr/bin/env bash\nexit 0\n")
        next_binary.chmod(0o700)
        self.env = {"PATH": os.environ["PATH"], "WGS_WORKSPACE": str(self.root / "var")}

    def start(self, **overrides):
        return subprocess.run(
            ["bash", str(self.root / "deploy/start.sh")], env={**self.env, **overrides},
            capture_output=True, text=True, timeout=10,
        )

    def test_start_prepares_search_before_application_processes(self):
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "var/events").read_text().splitlines(), ["elastic:start", "index"])
        self.assertIn("workspace-api started", result.stdout)
        self.assertIn("workspace-web started", result.stdout)

    def test_failure_prevents_web_and_api_start(self):
        result = self.start(FAIL_ELASTIC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((self.root / "var/run").glob("*.pid")))

    def test_external_mode_skips_managed_start_and_index_initialization(self):
        result = self.start(WGS_ELASTICSEARCH_MANAGED="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "var/events").exists())

    def test_status_and_stop_include_elasticsearch(self):
        for action in ("status", "stop"):
            (self.root / "var").mkdir(exist_ok=True)
            result = subprocess.run(
                ["bash", str(self.root / f"deploy/{action}.sh")],
                env=self.env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "var/events").read_text().splitlines(), ["elastic:status", "elastic:stop"])


class ClientCredentialTests(unittest.TestCase):
    """Exercise the real client adapter with dependency doubles, without a server."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.password_file = Path(self.temporary.name) / "client-password"
        self.password_file.write_text("synthetic-client-password\n")
        self.settings = types.SimpleNamespace(
            elasticsearch_url="http://127.0.0.1:9200", elasticsearch_index="wgs-knowledge",
            elasticsearch_api_key="", elasticsearch_username="wgs-platform",
            elasticsearch_password_file=self.password_file, embedding_dimensions=384,
        )
        client_module = types.ModuleType("elasticsearch")
        self.factory = client_module.Elasticsearch = Mock()
        config_module = types.ModuleType("wgs_fmt_platform.config")
        config_module.get_settings = lambda: self.settings
        client_spec = importlib.util.spec_from_file_location(
            "search_under_test", ROOT / "src/wgs_fmt_platform/infrastructure/search.py",
        )
        self.search = importlib.util.module_from_spec(client_spec)
        with patch.dict(managed.sys.modules, {
            "httpx": types.ModuleType("httpx"), "elasticsearch": client_module,
            "wgs_fmt_platform.config": config_module,
        }):
            client_spec.loader.exec_module(self.search)

    def test_password_file_becomes_basic_auth(self):
        self.search.HybridKnowledgeSearch()
        self.factory.assert_called_once_with(
            self.settings.elasticsearch_url, basic_auth=("wgs-platform", "synthetic-client-password"),
        )

    def test_external_api_key_takes_precedence_over_password_file(self):
        self.settings.elasticsearch_api_key = "synthetic-api-key"
        self.password_file.unlink()
        self.search.HybridKnowledgeSearch()
        self.factory.assert_called_once_with(self.settings.elasticsearch_url, api_key="synthetic-api-key")

    def test_empty_password_file_prevents_client_creation(self):
        self.password_file.write_text("\n")
        with self.assertRaisesRegex(ValueError, "password file is empty"):
            self.search.HybridKnowledgeSearch()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
