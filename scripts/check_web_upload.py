"""Exercise a built Next upload route against the real API with synthetic files.

Run in a disposable source copy with installed dependencies and a Web build made
with WGS_API_PORT=18503. Only loopback listeners and temporary runtime data are
used. The fake analysis worker sleeps; no sequencing analysis or databases run.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if not str(root).startswith("/tmp/fmt-upload-fix-"):
        raise SystemExit("Run this check in a disposable /tmp/fmt-upload-fix-* source copy.")
    web = root / "apps/workspace-web"
    for port in (18502, 18503):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    runtime = Path(tempfile.mkdtemp(prefix="synthetic-upload-", dir=root))
    worker = runtime / "fake-worker.sh"
    worker.write_text("#!/usr/bin/env bash\nsleep 120\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WGS_", "DEEPSEEK_", "ANTHROPIC_", "OPENAI_"))}
    env.update({
        "WGS_WORKSPACE": str(runtime), "WGS_APP_ROOT": str(root),
        "WGS_API_PORT": "18503", "WGS_BIOINFORMATICS_WORKER": str(worker),
        "PYTHONPATH": f"{root / 'src'}:{root / 'apps/workspace-api'}",
        "NEXT_TELEMETRY_DISABLED": "1",
    })
    processes = []
    logs = []
    started = time.monotonic()
    try:
        commands = [
            [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(root / "apps/workspace-api"), "--host", "127.0.0.1", "--port", "18503"],
            ["node", str(web / "node_modules/next/dist/bin/next"), "start", str(web), "--hostname", "127.0.0.1", "--port", "18502"],
        ]
        for name, command in zip(("api", "web"), commands):
            log = (runtime / f"{name}.log").open("wb")
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        with httpx.Client(base_url="http://127.0.0.1:18502", timeout=20, trust_env=False) as client:
            for _ in range(80):
                try:
                    if client.get("/backend/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("An isolated test service stopped unexpectedly.")
                time.sleep(0.2)
            else:
                raise RuntimeError("Isolated services did not become ready.")

            paths = []
            for mate, bases in ((1, "ACGT"), (2, "TGCA")):
                path = runtime / f"synthetic_R{mate}.fastq.gz"
                record = f"@synthetic/{mate}\n{bases * 38}\n+\n{'I' * 152}\n".encode()
                with gzip.open(path, "wb", compresslevel=0) as handle:
                    for _ in range(40000):
                        handle.write(record)
                paths.append(path)
            total = sum(p.stat().st_size for p in paths)
            assert total > 24 * 1024 * 1024
            with paths[0].open("rb") as r1, paths[1].open("rb") as r2:
                response = client.post("/backend/api/samples/upload", data={"sample_id": "synthetic_pair", "layout": "paired"},
                    files={"read1": (paths[0].name, r1), "read2": (paths[1].name, r2)})
            assert response.status_code == 202, (response.status_code, response.text[:500])
            job = json.loads((runtime / "upload-jobs/jobs/synthetic_pair.json").read_text())
            assert len(job["files"]) == 2
            for original, item in zip(paths, job["files"]):
                saved = Path(item["path"])
                assert item["bytes"] == original.stat().st_size == saved.stat().st_size
                assert item["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest() == hashlib.sha256(saved.read_bytes()).hexdigest()

            def chunks():
                boundary = "synthetic-boundary"
                for key, value in (("sample_id", "synthetic_chunked"), ("layout", "paired")):
                    yield f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
                for key, path in zip(("read1", "read2"), paths):
                    yield f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                    with path.open("rb") as handle:
                        while block := handle.read(65536):
                            yield block
                    yield b"\r\n"
                yield f"--{boundary}--\r\n".encode()

            response = client.post("/backend/api/samples/upload", content=chunks(), headers={"content-type": "multipart/form-data; boundary=synthetic-boundary"})
            assert response.status_code == 202, (response.status_code, response.text[:500])
            chunked = json.loads((runtime / "upload-jobs/jobs/synthetic_chunked.json").read_text())
            assert [f["sha256"] for f in chunked["files"]] == [f["sha256"] for f in job["files"]]

            with paths[0].open("rb") as handle:
                response = client.post("/backend/api/samples/upload", data={"sample_id": "synthetic_single", "layout": "single"}, files={"read1": (paths[0].name, handle)})
            assert response.status_code == 202, (response.status_code, response.text[:500])
            response = client.post("/backend/api/samples/upload", data={"sample_id": "synthetic_pair", "layout": "single"}, files={"read1": ("duplicate.fastq", b"@x\nAC\n+\nII\n")})
            assert response.status_code == 409 and "不能重复提交" in response.json()["detail"]
            response = client.post("/backend/api/samples/upload", data={"sample_id": "synthetic_invalid", "layout": "single"}, files={"read1": ("invalid.txt", b"invalid")})
            assert response.status_code == 422 and "不支持" in response.json()["detail"]
            assert not (runtime / "upload-jobs/jobs/synthetic_invalid.json").exists()
            assert client.get("/backend/health").status_code == 200
            processes[0].terminate()
            processes[0].wait(timeout=10)
            response = client.post("/backend/api/samples/upload", data={"sample_id": "synthetic_offline", "layout": "single"}, files={"read1": ("tiny.fastq", b"@x\nAC\n+\nII\n")})
            assert response.status_code == 502 and "连接失败" in response.json()["detail"]
        assert "Request body exceeded" not in (runtime / "web.log").read_text(errors="replace")
        print(json.dumps({"checks": 7, "pair_compressed_bytes": total, "stored_pair_hashes_match": True,
            "content_length_and_chunked_upload": "202", "single_end": "202", "duplicate": "409", "invalid_suffix": "422", "backend_offline": "502",
            "rewrite_truncation_warning": False, "elapsed_s": round(time.monotonic() - started, 2), "runtime": str(runtime)}, indent=2))
    except Exception:
        for name in ("api", "web"):
            path = runtime / f"{name}.log"
            if path.exists():
                print(f"Isolated {name} log:\n" + path.read_text(errors="replace")[-4500:], file=sys.stderr)
        raise
    finally:
        for path in (runtime / "upload-jobs/jobs").glob("*.json"):
            pid = json.loads(path.read_text()).get("pid")
            if pid:
                try: os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError: pass
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        for log in logs: log.close()


if __name__ == "__main__":
    main()
