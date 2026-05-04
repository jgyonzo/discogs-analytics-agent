# Contract: HTTP API

**Feature**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)

The agent exposes a FastAPI HTTP API at `http://localhost:8000`
when running locally. All endpoints return `application/json`
unless noted; all timestamps are ISO 8601 UTC.

Endpoints (V1):

1. `POST /query` — submit a question
2. `GET /threads/{thread_id}` — list runs in a thread
3. `GET /runs/{run_id}` — fetch a single run's full trace
4. `GET /artifacts/{artifact_id}` — fetch a chart file
5. `GET /health` — liveness + dependency check

Error envelope (used by all 4xx/5xx responses):

```json
{
  "error": {
    "code": "<short_machine_readable_code>",
    "message": "<human-readable message, no traceback>",
    "details": { ... }
  }
}
```

---

## 1. `POST /query`

Submit a natural-language analytical question.

**Request body**:

```json
{
  "thread_id": "optional-existing-thread-id",
  "message": "Show Techno releases by decade",
  "debug": false
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `thread_id` | string (UUID) | no | If omitted, a new thread is created. If supplied and unknown, returns `404`. |
| `message` | string | yes | Length 1 – 2000 chars (validated). |
| `debug` | boolean | no, default `false` | If `true`, the response includes the generated Python code; otherwise only the SQL. |

**Response — 200 OK** (success path):

```json
{
  "thread_id": "9f6c...e1",
  "run_id": "1a2b...c3",
  "response": "Generated a chart of Techno releases per decade.",
  "route": {
    "complexity": "simple",
    "selected_model": "gpt-4o-mini",
    "rationale": "Single table aggregation by decade."
  },
  "sql": "SELECT decade, COUNT(*) AS releases FROM release_unique_view ...",
  "code": null,
  "chart_artifact": {
    "artifact_id": "7d3e...f8",
    "url": "/artifacts/7d3e...f8",
    "type": "plotly_html"
  },
  "dataframe_preview": [
    {"decade": 1980, "releases": 12},
    {"decade": 1990, "releases": 35}
  ],
  "row_count": 5,
  "status": "succeeded",
  "carryover": {
    "turn_count": 0,
    "preamble": null
  }
}
```

When `debug = true`, `code` is the generated Python (string).

**Response — 200 OK** (controlled-failure paths):

The HTTP status is **200** for all four classified failure
modes (unsupported, clarification-needed, safety-exhausted,
validation-exhausted). The shape:

```json
{
  "thread_id": "...",
  "run_id": "...",
  "response": "I can't answer that — price data isn't part of the published catalog. Available metrics include: release counts, format breakdowns, style distributions, label diversity, master version counts.",
  "route": {
    "complexity": "unsupported",
    "selected_model": null,
    "rationale": "Question references a metric (price) not present in any allowlisted table."
  },
  "sql": null,
  "code": null,
  "chart_artifact": null,
  "dataframe_preview": [],
  "row_count": 0,
  "status": "failed_unsupported",
  "carryover": {"turn_count": 0, "preamble": null}
}
```

Status values for controlled failure:
- `failed_unsupported`
- `failed_clarification_needed`
- `failed_safety` (retries exhausted)
- `failed_validation` (retries exhausted)

For `failed_safety` / `failed_validation`, the response
explains *that* the agent couldn't safely / correctly answer,
*not* the specific traceback.

**Response — 4xx / 5xx**:

| Status | `code` | When |
|--------|--------|------|
| 400 | `invalid_request` | Body fails schema validation. |
| 404 | `thread_not_found` | `thread_id` supplied but doesn't exist. |
| 503 | `duckdb_unavailable` | DuckDB missing or unreadable; `/health` would also report not-OK. |
| 503 | `database_unavailable` | Postgres unreachable. |
| 500 | `internal_error` | Anything unclassified — only `error.message` is the short summary; the traceback goes to `agent_errors` not the response body. |

---

## 2. `GET /threads/{thread_id}`

List the runs of a thread, in chronological order.

**Path params**: `thread_id: UUID`.

**Query params**:
- `limit` (int, default 50, max 200)
- `offset` (int, default 0)

**Response — 200 OK**:

```json
{
  "thread_id": "9f6c...e1",
  "created_at": "2026-04-25T14:00:00Z",
  "updated_at": "2026-04-25T14:12:33Z",
  "status": "active",
  "run_count": 3,
  "runs": [
    {
      "run_id": "1a2b...c3",
      "user_query": "Show Techno releases by decade",
      "complexity": "simple",
      "status": "succeeded",
      "started_at": "2026-04-25T14:00:01Z",
      "finished_at": "2026-04-25T14:00:18Z",
      "latency_ms": 17000,
      "primary_artifact": {
        "artifact_id": "7d3e...f8",
        "url": "/artifacts/7d3e...f8",
        "type": "plotly_html"
      }
    },
    ...
  ]
}
```

**404**: `thread_not_found`.

---

## 3. `GET /runs/{run_id}`

Return a single run's full trace.

**Path params**: `run_id: UUID`.

**Query params**:
- `admin` (boolean, default `false`) — only honored when the
  request also presents the configured admin header
  (`X-Agent-Admin: <token>` — env `AGENT_ADMIN_TOKEN`,
  empty by default disables admin mode entirely). When admin
  mode is on, the response includes generated Python code and
  full tracebacks.

**Response — 200 OK**:

```json
{
  "run_id": "1a2b...c3",
  "thread_id": "9f6c...e1",
  "user_query": "Show Techno releases by decade",
  "status": "succeeded",
  "complexity": "simple",
  "selected_model": "gpt-4o-mini",
  "started_at": "2026-04-25T14:00:01Z",
  "finished_at": "2026-04-25T14:00:18Z",
  "latency_ms": 17000,
  "final_response": "Generated a chart...",
  "generated_sql": "SELECT decade, COUNT(*)...",
  "generated_code": null,
  "metadata": {
    "carryover": null,
    "route_rationale": "Single table aggregation by decade.",
    "retry_count": 0
  },
  "tool_calls": [
    {
      "tool_call_id": "...",
      "node_name": "load_schema",
      "tool_name": "dataset_schema_reader",
      "input": {"duckdb_path": "/app/data/published/duckdb/discogs.duckdb"},
      "output": {"has_master_fact": true, "tables_count": 5},
      "status": "succeeded",
      "latency_ms": 22,
      "created_at": "2026-04-25T14:00:01Z"
    },
    ...
  ],
  "model_usage": [
    {
      "usage_id": "...",
      "node_name": "router",
      "model_name": "gpt-4o-mini",
      "prompt_tokens": 312,
      "completion_tokens": 45,
      "total_tokens": 357,
      "estimated_cost_usd": 0.000063,
      "latency_ms": 480,
      "created_at": "2026-04-25T14:00:02Z"
    },
    ...
  ],
  "errors": [],
  "artifacts": [
    {
      "artifact_id": "7d3e...f8",
      "type": "plotly_html",
      "url": "/artifacts/7d3e...f8",
      "metadata": {"bytes": 4823, "chart_type": "bar", "row_count": 5},
      "created_at": "2026-04-25T14:00:18Z"
    }
  ]
}
```

When `admin=true` (and authenticated): `generated_code` is the
full Python string; `errors[].traceback` is populated for
`error_type = unexpected` rows.

**404**: `run_not_found`.

---

## 4. `GET /artifacts/{artifact_id}`

Fetch (or stream) the underlying chart file.

**Path params**: `artifact_id: UUID`.

**Response — 200 OK**:

- `Content-Type: text/html; charset=utf-8` (V1 always)
- Body: the `.html` file contents (Plotly inline-JS).

**404**: `artifact_not_found`.

**Notes**:
- The path on disk is resolved through Postgres
  (`agent_artifacts.path`), normalized, and asserted to be
  inside `ARTIFACTS_DIR` before the file is opened.
  Path-traversal attempts return 404 (not 400, to avoid
  leaking the existence of unrelated files).

---

## 5. `GET /health`

Liveness + dependency check. Used by Docker Compose
healthchecks and by US2 acceptance.

**Response — 200 OK** (status="ok"):

```json
{
  "status": "ok",
  "checks": {
    "duckdb": {
      "ok": true,
      "path": "/app/data/published/duckdb/discogs.duckdb",
      "tables_present": ["release_fact", "release_unique_view", "release_artist_bridge", "release_label_bridge", "master_fact"],
      "has_master_fact": true,
      "error": null
    },
    "postgres": {
      "ok": true,
      "error": null
    }
  },
  "version": "abc1234",
  "model_provider": "openai"
}
```

**Response — 503** (status="unavailable"):

When either check is `ok: false`. Same body shape; HTTP
status flips to 503 so Docker Compose / load balancers can
react.

| Check failure | DuckDB conditions | Postgres conditions |
|---------------|-------------------|---------------------|
| `ok = false` | file missing, unreadable, or any of the four core tables absent | `SELECT 1` fails or times out (>1 s) |
| `error` populated | short message (file path, error class) — no traceback | short message |

---

## 6. Cross-endpoint contract notes

- **`debug` flag does NOT bypass safety**. Setting `debug=true`
  on `/query` only widens the response payload; it does not
  relax SQL safety, sandbox restrictions, or the response
  synthesizer's no-traceback rule.
- **Idempotency**: `/query` is **not** idempotent (two calls
  with the same body produce two distinct `run_id`s). Clients
  that need idempotency should pass a stable `thread_id` and
  inspect the thread.
- **Pagination**: `/threads/{id}` is the only endpoint with
  pagination in V1. `/runs/{id}` is single-resource.
- **Versioning**: V1 endpoints are unversioned; future
  breaking changes will introduce `/v2/...`.

---

## 7. CLI mirror

The optional CLI (`python -m discogs_agent.cli ...`) wraps
`/query` with the same response semantics. Useful for
developer-loop iteration without `curl`/Postman.

```bash
python -m discogs_agent.cli query "Show releases by decade"
python -m discogs_agent.cli query "..." --thread-id <uuid>
python -m discogs_agent.cli query "..." --show-sql --show-code   # debug=true
```

The CLI is a thin wrapper — same Pydantic models, same error
codes — so it doesn't get its own contract document.
