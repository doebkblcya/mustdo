from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ModelProfile(str, Enum):
    cheap = "cheap"
    balanced = "balanced"
    strong = "strong"


class TodoCategory(str, Enum):
    work = "work"
    personal = "personal"
    learning = "learning"
    research = "research"
    technical = "technical"
    communication = "communication"
    follow_up = "follow_up"
    uncategorized = "uncategorized"


class TodoPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TodoStatus(str, Enum):
    open = "open"
    completed = "completed"
    archived = "archived"


class AnalyzeOptions(BaseModel):
    default_category: TodoCategory = TodoCategory.uncategorized


class AnalyzeRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    model_profile: ModelProfile = ModelProfile.balanced
    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)


class ModelInfo(BaseModel):
    provider: str
    name: str
    profile: ModelProfile


class AnalysisSummary(BaseModel):
    todo_count: int
    high_priority_count: int
    detected_language: str


class UsageInfo(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int


class TodoItem(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: TodoCategory
    priority: TodoPriority
    status: TodoStatus = TodoStatus.open
    assignee: str | None = None
    due_at: datetime | None = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    status: str
    model: ModelInfo
    summary: AnalysisSummary
    todos: list[TodoItem]
    usage: UsageInfo
    created_at: datetime


class ExtractedTodo(BaseModel):
    title: str
    description: str | None = None
    category: TodoCategory
    priority: TodoPriority
    assignee: str | None = None
    due_at: datetime | None = None


class ExtractionResult(BaseModel):
    items: list[ExtractedTodo]
    provider: str
    model_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class ModelExtractionResponse(BaseModel):
    items: list[ExtractedTodo]
