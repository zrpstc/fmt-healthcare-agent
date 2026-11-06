#!/usr/bin/env python3
"""Legacy PID check; lifecycle changes delegate to the unified project manager."""
import json
from pathlib import Path
import sys
from runtime import Config, classify, proc_record, main

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action == 'matches':
        try:
            config = Config.load()
            pid = int(Path(sys.argv[2]).read_text().strip())
            record = proc_record(pid)
            good = bool(record and classify(record, config.root) == 'workspace-api')
            raise SystemExit(0 if good else 1)
        except (OSError, ValueError, IndexError):
            raise SystemExit(1)
    raise SystemExit(main([action, '--component', 'workspace-api']))
