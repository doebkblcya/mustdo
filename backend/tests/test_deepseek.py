from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.services.deepseek import (  # noqa: E402
    DeepSeekParseError,
    NoTodoParsedError,
    OrganizeGroupOut,
    _loads_deepseek_json,
    organize_todos_with_deepseek,
    parse_todos_with_deepseek,
    validate_organize_groups,
)
from app.time_utils import today_date  # noqa: E402


class FakeDeepSeekResponse:
    def __init__(self, content: str | None) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
                "prompt_cache_hit_tokens": 5,
                "prompt_cache_miss_tokens": 15,
            },
            "choices": [{"message": {"content": self.content}}],
        }


class FakeDeepSeekClient:
    response_content: str | None = None
    last_json: dict | None = None

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, _url, *, headers, json):
        _ = headers
        FakeDeepSeekClient.last_json = json
        return FakeDeepSeekResponse(FakeDeepSeekClient.response_content)


class DeepSeekParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-flash",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_parse_todos_disables_thinking_mode(self) -> None:
        today = today_date().isoformat()
        FakeDeepSeekClient.response_content = (
            f'{{"items":[{{"content":"买菜","due_date":"{today}","due_time":null}}]}}'
        )
        FakeDeepSeekClient.last_json = None

        with patch("app.services.deepseek.httpx.AsyncClient", FakeDeepSeekClient):
            result = asyncio.run(parse_todos_with_deepseek("今天买菜"))

        self.assertEqual(result.items, [{"content": "买菜", "due_date": today, "due_time": None}])
        self.assertEqual(result.usage.total_tokens, 30)
        self.assertEqual(result.usage.cache_hit_tokens, 5)
        self.assertEqual(FakeDeepSeekClient.last_json["thinking"], {"type": "disabled"})
        self.assertEqual(FakeDeepSeekClient.last_json["response_format"], {"type": "json_object"})

    def test_system_prompt_mentions_keyboard_input(self) -> None:
        today = today_date().isoformat()
        FakeDeepSeekClient.response_content = (
            f'{{"items":[{{"content":"买菜","due_date":"{today}","due_time":null}}]}}'
        )
        FakeDeepSeekClient.last_json = None

        with patch("app.services.deepseek.httpx.AsyncClient", FakeDeepSeekClient):
            asyncio.run(parse_todos_with_deepseek("今天买菜"))

        system_content = FakeDeepSeekClient.last_json["messages"][0]["content"]
        self.assertIn("语音转写或键盘输入", system_content)

    def test_loads_deepseek_json_accepts_fenced_json(self) -> None:
        self.assertEqual(_loads_deepseek_json('```json\n{"items":[]}\n```'), {"items": []})

    def test_empty_deepseek_content_raises_parse_error(self) -> None:
        FakeDeepSeekClient.response_content = ""

        with patch("app.services.deepseek.httpx.AsyncClient", FakeDeepSeekClient):
            with self.assertRaises(DeepSeekParseError) as raised:
                asyncio.run(parse_todos_with_deepseek("今天买菜"))

        self.assertEqual(str(raised.exception), "DeepSeek 返回格式不合法")
        self.assertIn("JSONDecodeError", raised.exception.detail)

    def test_empty_items_raise_no_todo_error(self) -> None:
        FakeDeepSeekClient.response_content = '{"items":[]}'

        with patch("app.services.deepseek.httpx.AsyncClient", FakeDeepSeekClient):
            with self.assertRaises(NoTodoParsedError) as raised:
                asyncio.run(parse_todos_with_deepseek("今天天气不错"))

        self.assertEqual(str(raised.exception), "没有识别到需要新增的待办")


class OrganizeValidationTests(unittest.TestCase):
    """Deterministic checks on validate_organize_groups (no AI involved)."""

    def test_drops_foreign_ids_and_dedupes(self) -> None:
        groups = [
            OrganizeGroupOut(name="工作", todo_ids=[1, 999]),
            OrganizeGroupOut(name="采购", todo_ids=[2, 2, 3]),
        ]
        result = validate_organize_groups(groups, {1, 2, 3, 4})
        self.assertEqual(
            result,
            [
                {"name": "工作", "todo_ids": [1]},
                {"name": "采购", "todo_ids": [2, 3]},
                {"name": "其他", "todo_ids": [4]},
            ],
        )

    def test_merges_same_name_and_backfills_other(self) -> None:
        groups = [
            OrganizeGroupOut(name="工作", todo_ids=[1]),
            OrganizeGroupOut(name="工作", todo_ids=[2]),
            OrganizeGroupOut(name="其他", todo_ids=[3]),
        ]
        result = validate_organize_groups(groups, {1, 2, 3, 4})
        self.assertEqual(
            result,
            [
                {"name": "工作", "todo_ids": [1, 2]},
                {"name": "其他", "todo_ids": [3, 4]},
            ],
        )

    def test_keeps_all_named_groups_without_cap(self) -> None:
        groups = [OrganizeGroupOut(name=f"组{i}", todo_ids=[i]) for i in range(1, 9)]
        result = validate_organize_groups(groups, set(range(1, 9)))
        # 组数不截断：AI 返回几组就几组（收敛靠 prompt 提醒）
        self.assertEqual(len(result), 8)

    def test_ai_other_group_keeps_its_position(self) -> None:
        groups = [
            OrganizeGroupOut(name="工作", todo_ids=[1]),
            OrganizeGroupOut(name="其他", todo_ids=[2]),
            OrganizeGroupOut(name="个人", todo_ids=[3]),
        ]
        result = validate_organize_groups(groups, {1, 2, 3, 4})
        self.assertEqual(
            result,
            [
                {"name": "工作", "todo_ids": [1]},
                # 补漏项 4 并入 AI 原位「其他」
                {"name": "其他", "todo_ids": [2, 4]},
                {"name": "个人", "todo_ids": [3]},
            ],
        )

    def test_blank_name_falls_back_to_other(self) -> None:
        result = validate_organize_groups([OrganizeGroupOut(name="  ", todo_ids=[1])], {1, 2})
        self.assertEqual(result, [{"name": "其他", "todo_ids": [1, 2]}])


class OrganizeDeepSeekTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-flash",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_organize_calls_deepseek_and_validates(self) -> None:
        FakeDeepSeekClient.response_content = '{"groups":[{"name":"工作","todo_ids":[12,15]}]}'
        FakeDeepSeekClient.last_json = None
        items = [
            {"id": 12, "content": "写周报", "due_time": "17:00"},
            {"id": 15, "content": "回复客户", "due_time": None},
            {"id": 18, "content": "买牛奶", "due_time": None},
        ]

        with patch("app.services.deepseek.httpx.AsyncClient", FakeDeepSeekClient):
            result = asyncio.run(organize_todos_with_deepseek("today", items))

        # AI 漏掉的 18 被补入「其他」
        self.assertEqual(
            result.groups,
            [
                {"name": "工作", "todo_ids": [12, 15]},
                {"name": "其他", "todo_ids": [18]},
            ],
        )
        self.assertEqual(result.usage.total_tokens, 30)
        last = FakeDeepSeekClient.last_json
        self.assertEqual(last["thinking"], {"type": "disabled"})
        self.assertEqual(last["response_format"], {"type": "json_object"})
        user_msg = last["messages"][1]["content"]
        self.assertIn("12. 写周报（17:00）", user_msg)
        self.assertIn("15. 回复客户", user_msg)


if __name__ == "__main__":
    unittest.main()
