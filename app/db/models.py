from datetime import datetime

from sqlmodel import Field, SQLModel


class AnalysisRun(SQLModel, table=True):
    __tablename__ = "analysis_runs"

    id: str = Field(primary_key=True)
    content: str
    language: str
    timezone: str
    model_profile: str
    provider: str
    model_name: str
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int
    created_at: datetime


class TodoRecord(SQLModel, table=True):
    __tablename__ = "todos"

    id: str = Field(primary_key=True)
    analysis_id: str = Field(foreign_key="analysis_runs.id", index=True)
    title: str
    description: str | None = None
    category: str
    priority: str
    status: str
    assignee: str | None = None
    due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
