# MVP Implementation Plan

## Scope

Build the first usable backend for the todo analyzer.

The MVP assumes the user usually submits one short paragraph, not long meeting notes. Because of that, the first implementation uses one synchronous API call and one AI model call per request.

## Target Endpoint

```http
POST /api/v1/analyses
```

The endpoint accepts user text, extracts todo items, stores the analysis in SQLite, and returns the normalized response described in [api-design.md](./api-design.md).

## Non-Goals

The MVP will not include:

- Frontend UI.
- User authentication.
- Async job queue.
- Long document chunking.
- Multi-agent workflow.
- Calendar/reminder integration.
- Task editing endpoints.
- Historical search endpoints.

These can be added after the core analysis endpoint is stable.

## Architecture

```text
FastAPI route
  -> request schema validation
  -> todo analyzer service
  -> AI provider adapter
  -> model output schema validation
  -> response assembly
  -> SQLite persistence
  -> JSON response
```

The important design rule is: the model only produces fields that require language understanding. The backend produces all deterministic fields.

## Field Ownership

### Model Generates

```text
todos[].title
todos[].description
todos[].category
todos[].priority
todos[].assignee
todos[].due_at
```

### Backend Generates

```text
analysis_id
status
model.provider
model.name
model.profile
summary.todo_count
summary.high_priority_count
usage.input_tokens
usage.output_tokens
usage.cost_usd
usage.latency_ms
created_at
todos[].id
todos[].status
```

This keeps output tokens low and avoids asking the model to invent system metadata.

## Recommended Project Structure

```text
app/
  main.py
  core/
    config.py
    ids.py
  api/
    v1/
      analyses.py
  db/
    session.py
    models.py
  schemas/
    analysis.py
  services/
    todo_analyzer.py
    ai_provider.py
    mock_provider.py
tests/
  test_analyses_api.py
docs/
  api-design.md
  mvp-implementation-plan.md
```

## Dependencies

Use a small Python stack:

```text
fastapi
uvicorn
pydantic-settings
sqlmodel
httpx
python-ulid
pytest
```

AI SDK dependencies can wait until the mock endpoint works. The real provider can initially call an OpenAI-compatible HTTP endpoint with `httpx`, which keeps the provider layer portable.

## Step 1: Create FastAPI Skeleton

Create:

```text
app/main.py
app/api/v1/analyses.py
app/schemas/analysis.py
```

Implementation goal:

- App starts with `uvicorn`.
- `GET /health` returns `{ "status": "ok" }`.
- `POST /api/v1/analyses` exists.
- Request and response schemas match `api-design.md`.

At this step, the endpoint can return mock data and does not need SQLite.

## Step 2: Implement Pydantic Schemas

Define API schemas in `app/schemas/analysis.py`:

```text
AnalyzeRequest
AnalyzeOptions
AnalyzeResponse
TodoItem
ModelInfo
AnalysisSummary
UsageInfo
```

Use enums for:

```text
ModelProfile: cheap, balanced, strong
TodoCategory: work, personal, learning, research, technical, communication, follow_up, uncategorized
TodoPriority: low, medium, high
TodoStatus: open, completed, archived
```

For the MVP, `TodoStatus` should always be `open` in analysis responses.

## Step 3: Add Mock Analyzer

Create `app/services/todo_analyzer.py`.

The analyzer receives `AnalyzeRequest` and returns normalized todo items. In the first version, it can use a mock provider:

```text
AnalyzeRequest
  -> MockProvider.extract_todos()
  -> backend adds todo IDs and status
  -> response summary is computed
```

This lets us verify the endpoint contract before spending time on AI provider details.

## Step 4: Add SQLite Persistence

Create:

```text
app/db/session.py
app/db/models.py
```

Use two MVP tables:

```text
analysis_runs
todos
```

`analysis_runs` stores:

```text
id
content
language
timezone
model_profile
provider
model_name
status
input_tokens
output_tokens
cost_usd
latency_ms
created_at
```

`todos` stores:

```text
id
analysis_id
title
description
category
priority
status
assignee
due_at
created_at
updated_at
```

For the MVP, create tables automatically on startup. A migration tool can be added later when schema changes become more frequent.

## Step 5: Add AI Provider Adapter

Create `app/services/ai_provider.py`.

The adapter interface should be provider-neutral:

```python
class AIProvider:
    async def extract_todos(self, request: AnalyzeRequest, model_name: str) -> AIExtractionResult:
        ...
```

The result should contain:

```text
items
provider
model_name
input_tokens
output_tokens
cost_usd
```

The concrete provider can be:

```text
MockProvider
OpenAICompatibleProvider
```

This supports official OpenAI APIs and third-party OpenAI-compatible gateways without changing the route or database layer.

## Step 6: Real Model Call Strategy

Use one model call per request.

The model should return only this minimal shape:

```json
{
  "items": [
    {
      "title": "整理竞品截图",
      "description": "让小王整理竞品截图。",
      "category": "research",
      "priority": "medium",
      "assignee": "小王",
      "due_at": "2026-06-04T23:59:59+08:00"
    }
  ]
}
```

Do not ask the model to generate IDs, status, summaries, usage, or timestamps.

### Prompt Shape

Keep the static instruction short and stable:

```text
Extract actionable todo items from the user text.
Return only tasks that require action.
Use null when assignee or due_at is unknown.
Resolve relative time using current_datetime and timezone.
Do not invent deadlines, assignees, or details.
If no actionable task exists, return an empty items array.
```

Pass dynamic context separately:

```json
{
  "current_datetime": "2026-06-03T10:20:30+08:00",
  "timezone": "Asia/Shanghai",
  "language": "zh-CN",
  "default_category": "uncategorized",
  "content": "用户输入文本"
}
```

Static prompt first and dynamic content last helps keep future prompt caching effective.

## Step 7: Validation and Retry

Validate model output with Pydantic before saving.

MVP retry policy:

```text
1. Call selected model once.
2. If provider fails, return 502 model_failed.
3. If output does not match schema, retry once with the same model.
4. If retry still fails, return 502 invalid_model_output.
```

Do not add complex `cheap -> strong` fallback in the first implementation. Keep the first real provider simple, then add fallback after we collect examples.

## Step 8: Tests

Start with focused API tests:

```text
POST /api/v1/analyses returns 200 for valid content.
Empty content returns 422.
Returned todos have backend-generated IDs.
Returned todos always start with status=open.
Analysis and todos are saved to SQLite.
```

Mock the AI provider in tests so tests are stable and do not spend API tokens.

## Implementation Order

1. Create project skeleton and dependencies.
2. Implement schemas.
3. Implement mock endpoint response.
4. Add SQLite models and persistence.
5. Add tests for the mock-backed endpoint.
6. Add provider abstraction.
7. Add OpenAI-compatible provider.
8. Add schema validation and retry.
9. Update docs with run commands and environment variables.

## MVP Acceptance Criteria

The MVP is complete when:

- `uvicorn app.main:app --reload` starts the server.
- `GET /health` works.
- `POST /api/v1/analyses` accepts one paragraph of text.
- The endpoint returns the documented response shape.
- Every request is saved to SQLite.
- Tests pass without calling a real AI provider.
- Real AI provider can be enabled through environment variables.

## Future Extensions

After the MVP:

- Add `GET /api/v1/analyses/{analysis_id}`.
- Add task edit/complete endpoints.
- Add model fallback: `cheap -> balanced -> strong`.
- Add long-text chunking for meeting notes.
- Add history-based deduplication.
- Add frontend UI.
