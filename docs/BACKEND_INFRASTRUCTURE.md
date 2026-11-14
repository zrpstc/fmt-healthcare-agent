# Backend infrastructure

## Components

- Local SQLite (`var/db/wgs_agent.db`): users, conversations, messages, memory metadata, and audit records. MySQL is an explicit optional alternative via `WGS_DATABASE_URL`.
- Redis: short-term memory with TTL and long-term memory with an optional TTL.
- Elasticsearch: BM25 keyword search and dense-vector kNN search. The deployment scripts manage an authenticated, loopback-only Docker node by default.
- LitKG Claim API: relationship-graph evidence. Results are fused with Elasticsearch by reciprocal rank fusion (RRF).

## Configuration

Copy `.env.example` to `.env`. Single-server defaults use loopback service addresses. Important variables:

```text
WGS_WORKSPACE
WGS_DATABASE_URL
WGS_REDIS_URL
WGS_ELASTICSEARCH_URL
WGS_ELASTICSEARCH_INDEX
WGS_ELASTICSEARCH_MANAGED
WGS_ELASTICSEARCH_USERNAME
WGS_ELASTICSEARCH_PASSWORD_FILE
WGS_EMBEDDING_DIMENSIONS
WGS_CLAIM_API_URL
WGS_CLAIM_API_KNOWLEDGE_BASE_ID
WGS_GRAPH_TEXT_SEARCH_PATH
```

The embedding dimension is part of the Elasticsearch index mapping. Changing it requires creating a new index or reindexing existing documents.

## Initialize local data without starting services

Install the backend dependencies and initialize local SQLite schemas:

```bash
pip install -e '.[infra]'
python scripts/init_data.py
```

This does not start MySQL, Redis, Elasticsearch, LitKG, Web, or API services. Optional
MySQL, Redis, and LitKG services must be prepared separately. Later, `deploy/start.sh`
starts the managed Elasticsearch node, provisions a scoped application account,
and creates its index before starting the application. Set
`WGS_ELASTICSEARCH_MANAGED=false` to use an existing instance or omit Elasticsearch.
See [single-server architecture](SINGLE_SERVER.md#elasticsearch-随项目启动) for configuration,
Docker access requirements, persisted data volumes, and credential backups.

## API

```text
GET  /api/backend/health
POST /api/backend/schema/initialize
POST /api/backend/users
GET  /api/backend/users
POST /api/backend/memory
GET  /api/backend/memory/{user_id}?scope=short|long
POST /api/backend/knowledge/index
POST /api/backend/knowledge/search
```

The browser accesses these routes through `http://<server-ip>:18502/backend/api/backend/*`.

## Search flow

1. Search `title^2` and `content` with Elasticsearch BM25.
2. If a query embedding is supplied, run dense-vector kNN search.
3. Query LitKG for relationship claims and evidence.
4. Deduplicate records by ID and merge keyword, vector, and graph rankings with RRF.
5. Return partial results plus an `errors` array when any provider is unavailable.

The API never stores plaintext passwords. Passwords use salted PBKDF2-SHA256 with 310,000 iterations. Production authentication should add session/JWT issuance, rate limiting, email verification, and account recovery before exposing user endpoints publicly.
