from sqlmodel import Session

from app.db.models import AnalysisRun, TodoRecord
from app.schemas.analysis import AnalyzeRequest, AnalyzeResponse


def save_analysis(
    session: Session, request: AnalyzeRequest, response: AnalyzeResponse
) -> None:
    analysis = AnalysisRun(
        id=response.analysis_id,
        content=request.content,
        language=request.language,
        timezone=request.timezone,
        model_profile=request.model_profile.value,
        provider=response.model.provider,
        model_name=response.model.name,
        status=response.status,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=response.usage.cost_usd,
        latency_ms=response.usage.latency_ms,
        created_at=response.created_at,
    )

    todos = [
        TodoRecord(
            id=todo.id,
            analysis_id=response.analysis_id,
            title=todo.title,
            description=todo.description,
            category=todo.category.value,
            priority=todo.priority.value,
            status=todo.status.value,
            assignee=todo.assignee,
            due_at=todo.due_at,
            created_at=response.created_at,
            updated_at=response.created_at,
        )
        for todo in response.todos
    ]

    session.add(analysis)
    session.add_all(todos)
    session.commit()
