from __future__ import annotations

from typing import Any, NoReturn

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


HTTP_422_UNPROCESSABLE_CONTENT = 422

DEFAULT_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "请求参数不合法",
    status.HTTP_401_UNAUTHORIZED: "请先登录",
    status.HTTP_404_NOT_FOUND: "资源不存在",
    status.HTTP_409_CONFLICT: "资源冲突",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "不支持的媒体类型",
    HTTP_422_UNPROCESSABLE_CONTENT: "请求参数不合法",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "服务暂时不可用",
    status.HTTP_502_BAD_GATEWAY: "上游服务暂时不可用",
}

DEFAULT_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_502_BAD_GATEWAY: "upstream_error",
}


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def raise_api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=error_payload(code, message, details),
    )


def _default_code(status_code: int) -> str:
    return DEFAULT_CODES.get(status_code, "api_error")


def _default_message(status_code: int) -> str:
    return DEFAULT_MESSAGES.get(status_code, "请求失败")


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code") or _default_code(exc.status_code))
        message = str(exc.detail.get("message") or _default_message(exc.status_code))
        details = exc.detail.get("details")
    else:
        code = _default_code(exc.status_code)
        message = str(exc.detail or _default_message(exc.status_code))
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, details),
        headers=exc.headers,
    )


async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", []) if part != "body"),
            "message": error.get("msg", "参数不合法"),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_payload("validation_error", "请求参数不合法", details),
    )
