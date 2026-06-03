# API Design: Todo Analyzer

## Goal

Design a small FastAPI service that receives free-form text, asks an AI model to extract actionable tasks, validates the structured result, stores the analysis in SQLite, and returns a normalized to-do list.

This document focuses on the first core endpoint only.

## Core Endpoint

```http
POST /api/v1/analyses
```

Analyze one text input and return extracted to-do items.

For the MVP, this endpoint is synchronous. The client waits for the AI result in the same request. If model latency becomes a problem later, this can be extended with an async job API.

## Request

```json
{
  "content": "今天下午和产品开会，确认登录页改版方案。明天前让小王整理竞品截图，我周五写完技术方案。",
  "language": "zh-CN",
  "timezone": "Asia/Shanghai",
  "model_profile": "balanced",
  "options": {
    "default_category": "uncategorized"
  }
}
```

### Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `content` | string | yes | User input text to analyze. |
| `language` | string | no | Preferred output language. Default: `zh-CN`. |
| `timezone` | string | no | User timezone for relative dates and concrete times. Default should come from server config. |
| `model_profile` | string | no | Cost/quality preset: `cheap`, `balanced`, or `strong`. Default: `balanced`. |
| `options` | object | no | Analysis behavior switches. |

### Options

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `default_category` | string | `uncategorized` | Category used when no category is clear. |

## Response

```json
{
  "analysis_id": "01JZ8M9C8SKVX5Q2Q3E7T40K6D",
  "status": "completed",
  "model": {
    "provider": "openai",
    "name": "configured-balanced-model",
    "profile": "balanced"
  },
  "summary": {
    "todo_count": 3,
    "high_priority_count": 1,
    "detected_language": "zh-CN"
  },
  "todos": [
    {
      "id": "01JZ8M9F9V8JCN3VQ4K54DQVY7",
      "title": "确认登录页改版方案",
      "description": "与产品开会后确认登录页改版方案。",
      "category": "work",
      "priority": "high",
      "status": "open",
      "assignee": null,
      "due_at": "2026-06-03T15:00:00+08:00"
    },
    {
      "id": "01JZ8M9F9V52G9R2ZP0FYMVQT3",
      "title": "整理竞品截图",
      "description": "让小王在明天前整理竞品截图。",
      "category": "research",
      "priority": "medium",
      "status": "open",
      "assignee": "小王",
      "due_at": "2026-06-04T23:59:59+08:00"
    },
    {
      "id": "01JZ8M9F9V2SZZKJPM7GZV6WQW",
      "title": "写完技术方案",
      "description": "周五前完成技术方案。",
      "category": "technical",
      "priority": "medium",
      "status": "open",
      "assignee": "我",
      "due_at": "2026-06-05T23:59:59+08:00"
    }
  ],
  "usage": {
    "input_tokens": 128,
    "output_tokens": 430,
    "cost_usd": null,
    "latency_ms": 1460
  },
  "created_at": "2026-06-03T10:20:30+08:00"
}
```

## Response Fields

| Field | Type | Description |
| --- | --- | --- |
| `analysis_id` | string | Persisted analysis run ID. |
| `status` | string | `completed`, `failed`, or future `processing`. |
| `model` | object | Provider/model metadata used for this request. |
| `summary` | object | Small aggregate summary for UI display. |
| `todos` | array | Normalized tasks extracted from input. |
| `usage` | object | Token, cost, and latency metadata when available. |
| `created_at` | string | ISO 8601 timestamp. |

## Todo Item Schema

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Todo ID. |
| `title` | string | yes | Short actionable task title. |
| `description` | string/null | no | More context from the source text. |
| `category` | string | yes | Normalized category, such as `work`, `personal`, `research`, `technical`, `communication`, `follow_up`, or `uncategorized`. |
| `priority` | string | yes | `low`, `medium`, or `high`. |
| `status` | string | yes | Initial value is `open`. |
| `assignee` | string/null | no | Person responsible if mentioned. |
| `due_at` | string/null | no | ISO 8601 datetime with timezone, such as `2026-06-05T18:00:00+08:00`. Use null if unknown. |

## Error Responses

### Invalid Input

```http
422 Unprocessable Entity
```

```json
{
  "error": {
    "code": "invalid_input",
    "message": "content must contain at least 1 non-whitespace character"
  }
}
```

### Model Failure

```http
502 Bad Gateway
```

```json
{
  "error": {
    "code": "model_failed",
    "message": "AI provider failed to return a valid response",
    "analysis_id": "01JZ8M9C8SKVX5Q2Q3E7T40K6D"
  }
}
```

### Structured Output Validation Failure

```http
502 Bad Gateway
```

```json
{
  "error": {
    "code": "invalid_model_output",
    "message": "AI response did not match the expected todo schema",
    "analysis_id": "01JZ8M9C8SKVX5Q2Q3E7T40K6D"
  }
}
```

## FastAPI Model Draft

```python
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ModelProfile(str, Enum):
    cheap = "cheap"
    balanced = "balanced"
    strong = "strong"


class AnalyzeOptions(BaseModel):
    default_category: str = "uncategorized"


class AnalyzeRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    model_profile: ModelProfile = ModelProfile.balanced
    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)


class TodoItem(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: str
    priority: Literal["low", "medium", "high"]
    status: Literal["open", "completed", "archived"] = "open"
    assignee: str | None = None
    due_at: datetime | None = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    status: Literal["completed"]
    model: dict
    summary: dict
    todos: list[TodoItem]
    usage: dict
    created_at: datetime
```

## SQLite Mapping Draft

The endpoint can be implemented before the full database schema is final, but the response should map cleanly to these future tables:

| Table | Purpose |
| --- | --- |
| `analysis_runs` | One row per submitted text analysis. Stores content, language, timezone, model profile, provider, usage, status, and timestamps. |
| `todos` | One row per extracted todo item. Linked to `analysis_runs.id`. |
| `model_configs` | Optional future table for user-defined provider/model presets. For MVP, use environment variables first. |

## Design Decisions

1. Use a synchronous endpoint for the MVP because personal usage has low concurrency and simpler UX.
2. Keep `model_profile` separate from concrete model names so the app can switch providers without changing the frontend.
3. Store every analysis by default because the project is for personal history and later comparison between models.
4. Use `due_at` instead of `due_date` so tasks can include concrete times such as meetings, reminders, and deadlines.
5. Validate AI output against a strict schema before returning it to the client.

## Next Step

Create the FastAPI project skeleton with:

- `app/main.py`
- `app/api/v1/analyses.py`
- `app/schemas/analysis.py`
- `app/services/todo_analyzer.py`
- `app/services/ai_provider.py`
- `app/db/`

The first implementation can return mock structured data from `todo_analyzer.py`, then the AI provider adapter can be added after the API shape is stable.
