# Workspace API

This directory owns the HTTP boundary of the active system. Domain logic remains in
`src/wgs_agent` and `src/wgs_fmt_platform`; this package only composes those capabilities
for the Next.js workspace.

Run from the repository root:

```bash
python -m uvicorn app.main:app --app-dir apps/workspace-api --host 127.0.0.1 --port 18503
```

The browser uses `http://<server-ip>:18502/backend/*`; Next.js forwards those requests
to this loopback API. Runtime files and SQLite databases default to the repository's
`var/` directory. Run `python scripts/init_data.py` before first use. Both Python
and Next.js read the repository `.env`; see `docs/SINGLE_SERVER.md` for overrides.
