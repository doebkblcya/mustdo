from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.errors import http_exception_handler, raise_api_error, validation_exception_handler  # noqa: E402


class ErrorModelTests(unittest.TestCase):
    def test_http_exception_handler_wraps_legacy_string_detail(self) -> None:
        response = asyncio.run(
            http_exception_handler(
                None,
                HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在"),
            )
        )
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(payload, {"code": "not_found", "message": "待办不存在", "details": None})

    def test_raise_api_error_uses_structured_detail(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            raise_api_error(status.HTTP_400_BAD_REQUEST, "content_required", "内容不能为空")

        self.assertEqual(raised.exception.detail["code"], "content_required")
        self.assertEqual(raised.exception.detail["message"], "内容不能为空")

    def test_validation_handler_returns_field_details(self) -> None:
        response = asyncio.run(
            validation_exception_handler(
                None,
                RequestValidationError(
                    [
                        {
                            "loc": ("body", "content"),
                            "msg": "Field required",
                            "type": "missing",
                        }
                    ]
                ),
            )
        )
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["code"], "validation_error")
        self.assertEqual(payload["message"], "请求参数不合法")
        self.assertEqual(payload["details"][0]["field"], "content")


if __name__ == "__main__":
    unittest.main()
