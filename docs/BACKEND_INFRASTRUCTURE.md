# Backend infrastructure

## Components

- MySQL 8.4: users, conversations, messages, memory metadata, and audit records.
- Redis: short-term memory with TTL and long-term memory with an optional TTL.
- Elasticsearch: BM25 keyword search and dense-vector kNN search.
- LitKG Claim API: relationship-graph evidence. Results are fused with Elasticsearch by reciprocal rank fusion (RRF).

## Configuration

Copy `.env.example` to `.env` and replace every `change-me` value before deployment. Important variables:

```text
WGS_MYSQL_URL
WGS_REDIS_URL
WGS_ELASTICSEARCH_URL
WGS_ELASTICSEARCH_INDEX
WGS_EMBEDDING_DIMENSIONS
WGS_CLAIM_API_URL
WGS_CLAIM_API_KNOWLEDGE_BASE_IDS
WGS_GRAPH_TEXT_SEARCH_PATH
```

`WGS_CLAIM_API_KNOWLEDGE_BASE_IDS=auto` discovers the current catalog with
`GET /knowledge-bases` and searches every available knowledge base. Set a
comma-separated list such as `25,26` to restrict server-side retrieval. The
legacy singular `WGS_CLAIM_API_KNOWLEDGE_BASE_ID` remains available only for
older adapters and emergency fallback.

The embedding dimension is part of the Elasticsearch index mapping. Changing it requires creating a new index or reindexing existing documents.

## Start services

On a Docker-enabled host:

```bash
docker compose -f deploy/docker-compose.yml up -d mysql redis elasticsearch
```

Install the backend dependencies and initialize the SQLAlchemy schema and Elasticsearch index:

```bash
pip install -e '.[infra]'
curl -X POST http://127.0.0.1:8503/api/backend/schema/initialize
curl http://127.0.0.1:8503/api/backend/health
```

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

The platform API exposes the same router under `/v1/backend`.

## Search flow

1. Search `title^2` and `content` with Elasticsearch BM25.
2. If a query embedding is supplied, run dense-vector kNN search.
3. Query LitKG for relationship claims and evidence.
4. Deduplicate records by ID and merge keyword, vector, and graph rankings with RRF.
5. Return partial results plus an `errors` array when any provider is unavailable.

The API never stores plaintext passwords. Passwords use salted PBKDF2-SHA256 with 310,000 iterations. Production authentication should add session/JWT issuance, rate limiting, email verification, and account recovery before exposing user endpoints publicly.
