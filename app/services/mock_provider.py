from datetime import datetime, time, timedelta
from re import split
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas.analysis import (
    AnalyzeRequest,
    ExtractedTodo,
    ExtractionResult,
    TodoCategory,
    TodoPriority,
)


class MockProvider:
    provider = "mock"
    model_name = "mock-v0"

    async def extract_todos(self, request: AnalyzeRequest) -> ExtractionResult:
        timezone = self._get_timezone(request.timezone)
        now = datetime.now(timezone)
        sentences = self._candidate_sentences(request.content)

        items = [
            ExtractedTodo(
                title=self._title_from_sentence(sentence),
                description=sentence,
                category=self._category_from_sentence(sentence, request),
                priority=self._priority_from_sentence(sentence),
                assignee=self._assignee_from_sentence(sentence),
                due_at=self._due_at_from_sentence(sentence, now),
            )
            for sentence in sentences
        ]

        if not items and request.content.strip():
            content = request.content.strip()
            items.append(
                ExtractedTodo(
                    title=self._title_from_sentence(content),
                    description=content,
                    category=request.options.default_category,
                    priority=TodoPriority.medium,
                    assignee=None,
                    due_at=None,
                )
            )

        return ExtractionResult(
            items=items[:10],
            provider=self.provider,
            model_name=self.model_name,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
        )

    def _get_timezone(self, timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _candidate_sentences(self, content: str) -> list[str]:
        candidates = [item.strip() for item in split(r"[。！？!?；;\n]+", content)]
        action_words = (
            "做",
            "写",
            "整理",
            "确认",
            "提交",
            "完成",
            "处理",
            "跟进",
            "安排",
            "提醒",
            "开会",
            "沟通",
            "让",
            "需要",
            "要",
            "todo",
            "TODO",
        )
        return [
            sentence
            for sentence in candidates
            if sentence and any(word in sentence for word in action_words)
        ]

    def _title_from_sentence(self, sentence: str) -> str:
        cleaned = sentence.strip(" ，,。.；;")
        return cleaned[:40] or "处理待办事项"

    def _category_from_sentence(
        self, sentence: str, request: AnalyzeRequest
    ) -> TodoCategory:
        if any(word in sentence for word in ("代码", "技术", "接口", "数据库", "bug", "API")):
            return TodoCategory.technical
        if any(word in sentence for word in ("竞品", "调研", "资料", "研究")):
            return TodoCategory.research
        if any(word in sentence for word in ("开会", "沟通", "产品", "确认")):
            return TodoCategory.communication
        return request.options.default_category

    def _priority_from_sentence(self, sentence: str) -> TodoPriority:
        if any(word in sentence for word in ("紧急", "马上", "今天", "尽快")):
            return TodoPriority.high
        if any(word in sentence for word in ("有空", "之后", "低优")):
            return TodoPriority.low
        return TodoPriority.medium

    def _assignee_from_sentence(self, sentence: str) -> str | None:
        if "小王" in sentence:
            return "小王"
        if "我" in sentence:
            return "我"
        return None

    def _due_at_from_sentence(
        self, sentence: str, now: datetime
    ) -> datetime | None:
        if "今天" in sentence:
            if "下午" in sentence:
                return datetime.combine(now.date(), time(15, 0), tzinfo=now.tzinfo)
            if "晚上" in sentence:
                return datetime.combine(now.date(), time(21, 0), tzinfo=now.tzinfo)
            return datetime.combine(now.date(), time(23, 59, 59), tzinfo=now.tzinfo)

        if "明天" in sentence:
            return datetime.combine(
                now.date() + timedelta(days=1), time(23, 59, 59), tzinfo=now.tzinfo
            )

        weekdays = {
            "周一": 0,
            "周二": 1,
            "周三": 2,
            "周四": 3,
            "周五": 4,
            "周六": 5,
            "周日": 6,
            "周天": 6,
        }
        for label, weekday in weekdays.items():
            if label in sentence:
                delta = (weekday - now.weekday()) % 7
                if delta == 0:
                    delta = 7
                return datetime.combine(
                    now.date() + timedelta(days=delta),
                    time(23, 59, 59),
                    tzinfo=now.tzinfo,
                )

        return None
