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
    _loads_deepseek_json,
    parse_todos_with_deepseek,
)
from app.time_utils import today_date  # noqa: E402


class FakeDeepSeekResponse:
    def __init__(self, content: str | None) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


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

        self.assertEqual(result, [{"content": "买菜", "due_date": today, "due_time": None}])
        self.assertEqual(FakeDeepSeekClient.last_json["thinking"], {"type": "disabled"})
        self.assertEqual(FakeDeepSeekClient.last_json["response_format"], {"type": "json_object"})

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


if __name__ == "__main__":
    unittest.main()
