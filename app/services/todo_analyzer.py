from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings, get_settings
from app.core.ids import new_id
from app.schemas.analysis import (
    AnalysisSummary,
    AnalyzeRequest,
    AnalyzeResponse,
    ModelInfo,
    TodoItem,
    TodoPriority,
    TodoStatus,
    UsageInfo,
)
from app.services.mock_provider import MockProvider
from app.services.openai_compatible_provider import OpenAICompatibleProvider


class TodoAnalyzer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self._create_provider()

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        started = perf_counter()
        created_at = self._now(request.timezone)
        extraction = await self.provider.extract_todos(request)

        todos = [
            TodoItem(
                id=new_id(),
                title=item.title,
                description=item.description,
                category=item.category,
                priority=item.priority,
                status=TodoStatus.open,
                assignee=item.assignee,
                due_at=item.due_at,
            )
            for item in extraction.items
        ]

        latency_ms = int((perf_counter() - started) * 1000)

        return AnalyzeResponse(
            analysis_id=new_id(),
            status="completed",
            model=ModelInfo(
                provider=extraction.provider,
                name=extraction.model_name,
                profile=request.model_profile,
            ),
            summary=AnalysisSummary(
                todo_count=len(todos),
                high_priority_count=sum(
                    1 for item in todos if item.priority == TodoPriority.high
                ),
                detected_language=request.language,
            ),
            todos=todos,
            usage=UsageInfo(
                input_tokens=extraction.input_tokens,
                output_tokens=extraction.output_tokens,
                cost_usd=extraction.cost_usd,
                latency_ms=latency_ms,
            ),
            created_at=created_at,
        )

    def _now(self, timezone: str) -> datetime:
        try:
            return datetime.now(ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            return datetime.now(ZoneInfo("UTC"))

    def _create_provider(self) -> MockProvider | OpenAICompatibleProvider:
        if self.settings.ai_provider == "openai_compatible":
            return OpenAICompatibleProvider(self.settings)
        return MockProvider()
