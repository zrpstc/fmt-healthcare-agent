# Full project snapshot

This branch is a portable snapshot of the WGS-FMT-Agent-v2 application.

## Included

- Backend, frontend, agent, workflow, deployment, and test source code
- Reproducible Python and Node dependency manifests
- Bioinformatics runtime scripts and environment definitions
- FMT model training outputs, evaluation tables, and paper figures
- Reference tables used by the application
- Example analysis reports and visualizations
- Local literature index source documents

## Intentionally excluded

- The four external biological databases under the shared `databases` directory
- Real `.env` files, credentials, API keys, and private SSH material
- SQLite and other mutable database files
- Audit logs, process IDs, caches, and generated build directories
- `node_modules`, Next.js build output, Conda environments, and redistributable runtime archives
- Microsoft YaHei font binaries, which are local runtime assets and are not redistributable

The excluded databases and environments must be mounted or restored separately by following the deployment documentation and resource manifests in this repository.
