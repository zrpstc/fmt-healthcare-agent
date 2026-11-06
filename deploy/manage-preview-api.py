#!/usr/bin/env python3
"""Compatibility entry point; preview and normal API now share the same lifecycle."""
import sys
from runtime import main

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    raise SystemExit(main([action, '--component', 'workspace-api', *sys.argv[2:]]))
