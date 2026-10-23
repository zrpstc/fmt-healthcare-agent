#!/usr/bin/env python3
"""Diagnose this workspace's Elasticsearch auth without printing any credentials.

Only --start-existing changes runtime state: it starts the already-owned container.
No users/passwords, containers, volumes, or application records are modified.
"""

from __future__ import annotations

import argparse
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from manage_elasticsearch import (
    CONFIG_LABEL,
    ManagedElasticsearch,
    ManagedElasticsearchError,
)


def report(event: str, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def inspect_credentials(manager, container):
    password_file = manager.directory / "password"
    saved = password_file.read_text().strip() if password_file.is_file() else None
    container_password = next(
        (
            v.split("=", 1)[1]
            for v in container.get("Config", {}).get("Env", [])
            if v.startswith("ELASTIC_PASSWORD=")
        ),
        None,
    )
    details = {}
    for name in ("password", "client-password"):
        path = manager.directory / name
        if path.is_file():
            stat = path.stat()
            details[name] = {
                "present": True,
                "mode": oct(stat.st_mode & 0o777),
                "uid": stat.st_uid,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        else:
            details[name] = {"present": False}
    report(
        "credentials",
        files=details,
        container_bootstrap_present=bool(container_password),
        saved_matches_container_bootstrap=hmac.compare_digest(saved, container_password)
        if saved and container_password
        else None,
    )
    return saved, container_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-existing", action="store_true")
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.duration <= 180:
        parser.error("duration must be 1..180 seconds")
    manager = ManagedElasticsearch()
    manager._configure()
    container = manager._inspect("container", manager.name)
    if not container:
        raise ManagedElasticsearchError(
            "No existing managed container; diagnosis will not create one"
        )
    manager._owned(container)
    volume = manager._inspect("volume", manager.volume)
    if not volume:
        raise ManagedElasticsearchError("Managed data volume is missing")
    manager._owned(volume, volume=True)
    binding = container.get("HostConfig", {}).get("PortBindings", {}).get("9200/tcp")
    if container["Config"]["Labels"].get(CONFIG_LABEL) != manager.fingerprint or binding != [
        {"HostIp": "127.0.0.1", "HostPort": str(manager.port)}
    ]:
        raise ManagedElasticsearchError("Existing managed container configuration differs")
    state = container.get("State", {})
    report(
        "container",
        name=manager.name,
        state=state.get("Status"),
        started=state.get("StartedAt"),
        finished=state.get("FinishedAt"),
        exit_code=state.get("ExitCode"),
        workspace=str(manager.workspace),
    )
    saved, initial = inspect_credentials(manager, container)
    if not state.get("Running"):
        if not args.start_existing:
            report(
                "not_running", next_step="Run with --start-existing to probe startup authentication"
            )
            return 0
        manager._docker("container", "start", manager.name)
        report("started_existing", name=manager.name)
    started = time.monotonic()
    attempts, successes = {}, {}
    candidates = [("saved_password", saved)]
    if initial and saved and not hmac.compare_digest(saved, initial):
        candidates.append(("container_bootstrap", initial))
    while time.monotonic() - started < args.duration:
        elapsed = round(time.monotonic() - started, 1)
        for source, password in candidates:
            if not password or source in successes:
                continue
            try:
                value = manager._request("GET", "/_security/_authenticate", password)
                status = 200
                if value.get("username") == "elastic":
                    successes[source] = elapsed
            except HTTPError as exc:
                status = exc.code
            except (URLError, TimeoutError, OSError, ValueError):
                status = "not_ready"
            if attempts.get(source) != status:
                report("auth_transition", source=source, elapsed_seconds=elapsed, status=status)
                attempts[source] = status
        if "saved_password" in successes:
            break
        time.sleep(2)
    output = manager._docker("container", "logs", "--tail", "150", manager.name)
    log_counts = {
        "authentication_failed": output.lower().count("failed to authenticate"),
        "security_index_unavailable": sum(
            output.lower().count(term)
            for term in (
                "security index is not yet available",
                "security index is unavailable",
                "unavailable_shards_exception",
                "security index does not exist",
            )
        ),
        "node_started": output.lower().count('"message":"started'),
    }
    report(
        "summary",
        duration_seconds=round(time.monotonic() - started, 1),
        latest_auth_status=attempts,
        first_success_seconds=successes,
        log_signals=log_counts,
        container_left_running=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ManagedElasticsearchError, OSError, ValueError) as exc:
        report(
            "diagnostic_error",
            error_type=type(exc).__name__,
            detail="Cannot inspect managed Elasticsearch; run through sudo and the project deployment environment",
        )
        raise SystemExit(1)
