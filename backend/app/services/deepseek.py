from __future__ import annotations

import json
from datetime import date

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.schemas import TIME_RE
from app.time_utils import today_date


class DeepSeekParseError(RuntimeError):
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


def _system_prompt(today: date) -> str:
    return f"""
你是一个待办事项解析器，只能输出 JSON。

当前日期：{today.isoformat()}
时区：Asia/Shanghai

任务：把用户语音转写文本拆分成待办数组。

规则：
1. 只处理新增待办，不输出修改、删除、完成等操作。
2. 如果用户整段话是在修改、删除、取消或完成已有事项，且没有新增事项，返回空数组。
3. 每个待办必须包含 content、due_date、due_time。
4. due_date 使用 YYYY-MM-DD。
5. 没有明确日期时，due_date 使用当前日期。
6. 模糊日期也使用当前日期，例如“有空”“回头”“改天”“哪天”。
7. 如果用户说的是过去日期，也使用当前日期，不能返回过去日期。
8. “今天”是当前日期，“明天”是当前日期后一天。
9. “周五”解析为不早于当前日期的最近一个周五；如果当天就是周五，则为当前日期。
10. “下周五”解析为下一个自然周的周五。
11. “月底”解析为当前月份最后一天。
12. due_time 只能是 null 或 HH:MM。
13. 没有明确具体时间时，due_time 为 null。
14. “上午”“下午”“晚上”“早上”等模糊时段不能转成具体时间，due_time 为 null。
15. “下午三点”“15点”“9:30”这类明确时间才转为 24 小时 HH:MM。
16. content 要去掉日期和时间表达，保留动作和对象。
17. 最多返回 20 条待办。

输出格式必须是：
{{
  "items": [
    {{"content": "买菜", "due_date": "{today.isoformat()}", "due_time": null}}
  ]
}}
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
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DeepSeekParseError("DeepSeek 请求失败") from exc

    try:
        content = response.json()["choices"][0]["message"]["content"]
        parsed_json = json.loads(content)
        parsed = ParsedTodoPayload.model_validate(parsed_json)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise DeepSeekParseError("DeepSeek 返回格式不合法") from exc

    if not parsed.items:
        raise DeepSeekParseError("DeepSeek 未解析出待办")

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
