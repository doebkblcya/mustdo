from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.schemas import TIME_RE
from app.time_utils import today_date


logger = logging.getLogger("uvicorn.error")
_deepseek_client: httpx.AsyncClient | None = None
_deepseek_client_lock = threading.Lock()


def get_deepseek_client() -> httpx.AsyncClient:
    global _deepseek_client
    if _deepseek_client is None:
        with _deepseek_client_lock:
            if _deepseek_client is None:
                _deepseek_client = httpx.AsyncClient(timeout=35)
    return _deepseek_client


async def close_deepseek_client() -> None:
    global _deepseek_client
    with _deepseek_client_lock:
        if _deepseek_client is not None:
            await _deepseek_client.aclose()
            _deepseek_client = None


class DeepSeekParseError(RuntimeError):
    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class NoTodoParsedError(DeepSeekParseError):
    pass


class ParsedTodoItem(BaseModel):
    content: str = Field(min_length=1, max_length=200)
    due_date: date
    due_time: str | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("content is required")
        return cleaned

    @field_validator("due_time")
    @classmethod
    def validate_due_time(cls, value: str | None) -> str | None:
        if value in {"", None}:
            return None
        if not TIME_RE.fullmatch(value):
            raise ValueError("due_time must be HH:MM")
        return value


class ParsedTodoPayload(BaseModel):
    items: list[ParsedTodoItem]


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _system_prompt(today: date) -> str:
    from datetime import timedelta

    tomorrow = today + timedelta(days=1)
    days_until_fri = (4 - today.weekday()) % 7
    if days_until_fri == 0:
        days_until_fri = 7
    next_friday = today + timedelta(days=days_until_fri)
    next_week_friday = next_friday + timedelta(days=7)

    weekday_cn = "一二三四五六日"[today.weekday()]
    day_after_tomorrow = today + timedelta(days=2)
    three_days_later = today + timedelta(days=3)

    return f"""
你是一个待办事项解析器。把用户输入文本（语音转写或键盘输入）拆分成待办数组。只输出 JSON。

当前日期：{today.isoformat()}（周{weekday_cn}），时区 Asia/Shanghai

规则：
1. 只处理新增待办，不处理修改、删除、完成已有事项。没有新增事项则返回空数组 []。
2. due_date 格式 YYYY-MM-DD。没有明确日期（含"有空""回头""改天""哪天"等）默认今天；过去日期也修正为今天。
3. "今天"={today.isoformat()}，"明天"={tomorrow.isoformat()}，"后天"={day_after_tomorrow.isoformat()}，"大后天"={three_days_later.isoformat()}。
4. "周X"=不早于今天的最近一个周X；"下周X"=下一个自然周的周X。当前周五={next_friday.isoformat()}，下周五={next_week_friday.isoformat()}。
5. "月底"=当月最后一天。
6. due_time 为 null 或 HH:MM。仅"下午三点""15点""9:30"等明确时间才转 24 小时制；"上午""下午""晚上""早上"等模糊时段 due_time=null。
7. content 去掉日期和时间表达，只保留动作和对象。
8. 同一地点/平台/场景的多个动作合并为一条待办（如"淘宝买A还有B"合并为一条）；不同地点/场景才拆分。
9. 最多返回 20 条。

示例：
输入："明天下午三点买菜"
输出：{{"items":[{{"content":"买菜","due_date":"{tomorrow.isoformat()}","due_time":"15:00"}}]}}

输入："淘宝买螺丝还有双面胶，周五去超市买牛奶"
输出：{{"items":[{{"content":"淘宝买螺丝和双面胶","due_date":"{today.isoformat()}","due_time":null}},{{"content":"超市买牛奶","due_date":"{next_friday.isoformat()}","due_time":null}}]}}

输入："有空把报告写完"
输出：{{"items":[{{"content":"写完报告","due_date":"{today.isoformat()}","due_time":null}}]}}

输入："下周五下午两点开会，明天交房租"
输出：{{"items":[{{"content":"开会","due_date":"{next_week_friday.isoformat()}","due_time":"14:00"}},{{"content":"交房租","due_date":"{tomorrow.isoformat()}","due_time":null}}]}}
""".strip()


async def parse_todos_with_deepseek(transcript: str) -> list[dict[str, str | None]]:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise DeepSeekParseError("DeepSeek 配置缺失")

    today = today_date()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": _system_prompt(today)},
            {"role": "user", "content": transcript},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    try:
        client = get_deepseek_client()
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = f"status={exc.response.status_code} body={exc.response.text[:300]}"
        raise DeepSeekParseError("DeepSeek 请求失败", detail=detail) from exc
    except httpx.HTTPError as exc:
        raise DeepSeekParseError("解析服务连接失败", detail=repr(exc)) from exc

    try:
        content = response.json()["choices"][0]["message"]["content"]
        parsed_json = _loads_deepseek_json(content)
        parsed = ParsedTodoPayload.model_validate(parsed_json)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        detail = _format_parse_detail(exc, content if "content" in locals() else None)
        raise DeepSeekParseError("DeepSeek 返回格式不合法", detail=detail) from exc

    if not parsed.items:
        raise NoTodoParsedError("没有识别到需要新增的待办")

    normalized: list[dict[str, str | None]] = []
    for item in parsed.items[:20]:
        due_date = item.due_date
        if due_date < today:
            due_date = today
        normalized.append(
            {
                "content": item.content,
                "due_date": due_date.isoformat(),
                "due_time": item.due_time,
            }
        )

    return normalized


def _loads_deepseek_json(content: object) -> object:
    if not isinstance(content, str) or not content.strip():
        raise json.JSONDecodeError("empty content", "", 0)

    cleaned = content.strip()
    fenced = JSON_BLOCK_RE.fullmatch(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)


def _format_parse_detail(exc: Exception, content: object) -> str:
    preview = content[:300] if isinstance(content, str) else repr(content)
    return f"{type(exc).__name__}: {exc}; content={preview!r}"
