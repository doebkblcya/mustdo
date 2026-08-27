from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
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
    def __init__(self, message: str, *, detail: str | None = None, usage: TokenUsage | None = None) -> None:
        super().__init__(message)
        self.detail = detail
        # Token accounting is kept even when business parsing fails: if
        # DeepSeek produced usage, we must still count it (soft cap). Network
        # failures that never produced a response have usage=None.
        self.usage = usage


class NoTodoParsedError(DeepSeekParseError):
    pass


@dataclass(frozen=True)
class TokenUsage:
    """Token counts lifted straight from the DeepSeek response ``usage``.

    ``total_tokens`` is the billing/limit figure; the others are retained so
    the admin console can show breakdowns (input/completion/cache).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    @classmethod
    def from_response(cls, data: dict) -> TokenUsage:
        usage = data.get("usage") or {}
        return cls(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
            cache_miss_tokens=int(usage.get("prompt_cache_miss_tokens", 0)),
        )


@dataclass(frozen=True)
class ParseOutcome:
    """Business result of an AI parse, plus the token usage to meter."""

    items: list[dict[str, str | None]]
    usage: TokenUsage


@dataclass(frozen=True)
class OrganizeOutcome:
    """Business result of an AI organize, plus the token usage to meter."""

    groups: list[dict[str, object]]
    usage: TokenUsage


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


async def parse_todos_with_deepseek(transcript: str) -> ParseOutcome:
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

    data = None
    usage = None
    try:
        data = response.json()
        usage = TokenUsage.from_response(data)
        content = data["choices"][0]["message"]["content"]
        parsed_json = _loads_deepseek_json(content)
        parsed = ParsedTodoPayload.model_validate(parsed_json)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        detail = _format_parse_detail(exc, content if "content" in locals() else None)
        # usage may be None if the response body failed to parse before a usage
        # block was read; report zero usage in that case.
        raise DeepSeekParseError(
            "DeepSeek 返回格式不合法",
            detail=detail,
            usage=usage if usage is not None else TokenUsage(),
        ) from exc

    if not parsed.items:
        raise NoTodoParsedError("没有识别到需要新增的待办", usage=usage)

    normalized: list[dict[str, str | None]] = []
    for item in parsed.items[:20]:
        due_date = item.due_date
        due_date = max(due_date, today)
        normalized.append(
            {
                "content": item.content,
                "due_date": due_date.isoformat(),
                "due_time": item.due_time,
            }
        )

    return ParseOutcome(items=normalized, usage=usage)


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


# ============================================================
# AI 动态整理（今天视图）
# ============================================================


class OrganizeGroupOut(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    todo_ids: list[int] = Field(default_factory=list)


class OrganizePayload(BaseModel):
    groups: list[OrganizeGroupOut] = Field(default_factory=list)


def _organize_system_prompt() -> str:
    return """你是待办事项整理助手。根据待办之间的语义、场景、地点或共同目标，把它们分成几组，每组起一个简短组名。只输出 JSON。

规则：
1. 组名 2 至 6 个汉字，要贴合组内待办的实际内容，让用户一眼能看出这组是什么（如“客户跟进”“家务采购”“文档整理”），避免“工作”“采购”“个人”这类笼统的分类名。
2. 每条待办恰好分到一组；todo_ids 必须是输入列表中的 ID，不要发明 ID。
3. 分组数量不宜过多，如果分组过多请适当合并同类分组、收敛归类。
4. 与其他事项关系较弱的待办放入名为“其他”的组。
5. 只输出 JSON：{"groups":[{"name":"组名","todo_ids":[1,2]}]}""".strip()


def _organize_user_prompt(view: str, items: list[dict[str, object]]) -> str:
    lines = []
    for item in items:
        line = f"{item['id']}. {item['content']}"
        if item.get("due_time"):
            line += f"（{item['due_time']}）"
        lines.append(line)
    return f"当前视图：{view}\n待办列表（ID. 内容（时间））：\n" + "\n".join(lines)


def validate_organize_groups(
    groups: list[OrganizeGroupOut],
    valid_ids: set[int],
) -> list[dict[str, object]]:
    """Normalize AI grouping output.

    - todo_ids not present in valid_ids are dropped (foreign IDs).
    - Duplicate IDs keep their first occurrence.
    - Groups with the same name are merged, preserving order — an AI-generated
      "其他" group stays where the AI placed it.
    - Todos missing from every group are backfilled into "其他".

    Group count is intentionally unconstrained here: the prompt tells the AI
    to merge and converge when there are too many groups.
    """
    seen: set[int] = set()
    by_name: dict[str, list[int]] = {}
    for group in groups:
        name = " ".join(group.name.strip().split())[:20] or "其他"
        ids: list[int] = []
        for todo_id in group.todo_ids:
            if todo_id in valid_ids and todo_id not in seen:
                seen.add(todo_id)
                ids.append(todo_id)
        if not ids:
            continue
        by_name.setdefault(name, []).extend(ids)
    missing = sorted(valid_ids - seen)
    if missing:
        by_name.setdefault("其他", []).extend(missing)
    return [{"name": name, "todo_ids": todo_ids} for name, todo_ids in by_name.items()]


async def organize_todos_with_deepseek(
    view: str,
    items: list[dict[str, object]],
) -> OrganizeOutcome:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise DeepSeekParseError("DeepSeek 配置缺失")

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": _organize_system_prompt()},
            {"role": "user", "content": _organize_user_prompt(view, items)},
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

    data = None
    content = None
    try:
        client = get_deepseek_client()
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        usage = TokenUsage.from_response(data)
        content = data["choices"][0]["message"]["content"]
        parsed = OrganizePayload.model_validate(_loads_deepseek_json(content))
    except httpx.HTTPStatusError as exc:
        detail = f"status={exc.response.status_code} body={exc.response.text[:300]}"
        raise DeepSeekParseError("DeepSeek 请求失败", detail=detail) from exc
    except httpx.HTTPError as exc:
        raise DeepSeekParseError("整理服务连接失败", detail=repr(exc)) from exc
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        detail = _format_parse_detail(exc, content)
        # data may or may not have set `usage` before the failure; default to
        # zero usage if the response never carried a usage block.
        raise DeepSeekParseError(
            "DeepSeek 返回格式不合法",
            detail=detail,
            usage=TokenUsage.from_response(data) if data is not None else None,
        ) from exc

    return OrganizeOutcome(
        groups=validate_organize_groups(parsed.groups, {item["id"] for item in items}),
        usage=usage,
    )
