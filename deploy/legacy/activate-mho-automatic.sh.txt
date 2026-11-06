#!/usr/bin/env bash
set -Eeuo pipefail
APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"
exec "$APP_ROOT/.venv/bin/python" - "$APP_ROOT" <<'PY'
import json,os,subprocess,sys,time,urllib.request
from pathlib import Path

root=Path(sys.argv[1]).resolve()
if os.geteuid()!=0:
    print(json.dumps({'status':'blocked','code':'root_required'}))
    raise SystemExit(2)
sys.path.insert(0,str(root/'src'))
from dotenv import load_dotenv
load_dotenv(root/'.env',override=False)
from wgs_agent.pipeline import mho_workflow as workflow
from wgs_agent.reporting import mho

log_dir=root/'var/logs'
log_dir.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
try:
    if not workflow.enabled():raise ValueError()
    mho.load_bundle(mho.reference_dir())
    _,exe,tools,_=workflow._configuration()
    if not workflow._verify_version(exe,tools):raise ValueError()
except Exception:
    print(json.dumps({'status':'failed','code':'checks_failed'}))
    raise SystemExit(1)

activation_log=log_dir/'mho-automatic-activation.log'
with activation_log.open('ab',buffering=0) as log:
    result=subprocess.run(['bash',str(root/'deploy/restart-report-api.sh')],
        cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print(json.dumps({'status':'failed','code':'checks_failed'}))
    raise SystemExit(1)

port=int(os.environ.get('WGS_API_PORT','8503'))
running=False
for _ in range(20):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
            running=response.status==200
        if running:break
    except Exception:pass
    time.sleep(0.5)
if not running:
    print(json.dumps({'status':'failed','code':'not_ready'}))
    raise SystemExit(1)

state_dir=mho.profiles_dir()/'.workflow'
state_dir.mkdir(parents=True,exist_ok=True,mode=0o750)
pid_file=state_dir/'backfill.pid'
backfill_running=False
try:
    pid=int(pid_file.read_text())
    os.kill(pid,0)
    arguments=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    backfill_running=(b'wgs_agent.pipeline.mho_workflow' in arguments and b'backfill' in arguments)
except (OSError,ValueError):pass
started=False
if not backfill_running:
    environment=dict(os.environ,PYTHONPATH=str(root/'src'),PYTHONDONTWRITEBYTECODE='1')
    with (log_dir/'mho-automatic-backfill.log').open('ab',buffering=0) as log:
        process=subprocess.Popen([str(root/'.venv/bin/python'),'-m',
            'wgs_agent.pipeline.mho_workflow','backfill'],cwd=root,env=environment,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            start_new_session=True,close_fds=True)
    pid_file.write_text(str(process.pid)+'\n')
    started=True
facts={'status':'activated','activated':True,'service_running':True,'backfill_started':started}
status_file=root/'tmp/mho-automatic-activation-status.json'
status_file.write_text(json.dumps(facts)+'\n')
status_file.chmod(0o644)
print(json.dumps(facts))
PY
