from datetime import datetime
import json
from json import JSONDecodeError
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.analysis import (
    AnalyzeRequest,
    ExtractionResult,
    ModelExtractionResponse,
    ModelProfile,
    TodoCategory,
    TodoPriority,
)
from app.services.exceptions import (
    AIProviderConfigError,
    AIProviderError,
    InvalidModelOutputError,
)


SYSTEM_PROMPT = """Extract actionable todo items from the user text.
Return only tasks that require action.
Use the requested language for title and description.
Use null when assignee or due_at is unknown.
Resolve relative time using current_datetime and timezone.
Do not invent deadlines, assignees, or details.
If no actionable task exists, return an empty items array."""


class OpenAICompatibleProvider:
    provider = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_todos(self, request: AnalyzeRequest) -> ExtractionResult:
        model_name = self._model_name(request.model_profile)
        payload = self._build_payload(request, model_name)
        url = f"{self.settings.ai_base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.ai_request_timeout_seconds
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AIProviderError(
                f"AI provider returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError("AI provider request failed") from exc

        data = response.json()
        model_output = self._extract_message_content(data)
        parsed = self._parse_model_output(model_output)
        usage = data.get("usage") or {}

        return ExtractionResult(
            items=parsed.items,
            provider=self.provider,
            model_name=model_name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cost_usd=None,
        )

    def _api_key(self) -> str:
        if not self.settings.ai_api_key:
            raise AIProviderConfigError("AI_API_KEY is required")
        return self.settings.ai_api_key

    def _model_name(self, profile: ModelProfile) -> str:
        model_by_profile = {
            ModelProfile.cheap: self.settings.ai_model_cheap,
            ModelProfile.balanced: self.settings.ai_model_balanced,
            ModelProfile.strong: self.settings.ai_model_strong,
        }
        model_name = (
            model_by_profile.get(profile)
            or self.settings.ai_model_balanced
            or self.settings.ai_model_cheap
            or self.settings.ai_model_strong
        )
        if not model_name:
            raise AIProviderConfigError(
                "At least one AI_MODEL_* value is required for openai_compatible"
            )
        return model_name

    def _build_payload(self, request: AnalyzeRequest, model_name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_datetime": self._current_datetime(
                                request.timezone
                            ),
                            "timezone": request.timezone,
                            "language": request.language,
                            "default_category": request.options.default_category.value,
                            "allowed_categories": [
                                item.value for item in TodoCategory
                            ],
                            "allowed_priorities": [
                                item.value for item in TodoPriority
                            ],
                            "content": request.content,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": self.settings.ai_temperature,
            "max_tokens": self.settings.ai_max_output_tokens,
        }

        if self.settings.ai_prompt_cache_key:
            payload["prompt_cache_key"] = self.settings.ai_prompt_cache_key

        response_format = self._response_format()
        if response_format:
            payload["response_format"] = response_format

        return payload

    def _response_format(self) -> dict[str, Any] | None:
        if self.settings.ai_response_format == "none":
            return None
        if self.settings.ai_response_format == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "todo_extraction",
                "schema": self._json_schema(),
                "strict": True,
            },
        }

    def _json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "maxItems": 30,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "title",
                            "description",
                            "category",
                            "priority",
                            "assignee",
                            "due_at",
                        ],
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": ["string", "null"]},
                            "category": {
                                "type": "string",
                                "enum": [item.value for item in TodoCategory],
                            },
                            "priority": {
                                "type": "string",
                                "enum": [item.value for item in TodoPriority],
                            },
                            "assignee": {"type": ["string", "null"]},
                            "due_at": {
                                "type": ["string", "null"],
                                "description": "ISO 8601 datetime with timezone, or null.",
                            },
                        },
                    },
                }
            },
        }

    def _current_datetime(self, timezone: str) -> str:
        try:
            return datetime.now(ZoneInfo(timezone)).isoformat()
        except ZoneInfoNotFoundError:
            return datetime.now(ZoneInfo("UTC")).isoformat()

    def _extract_message_content(self, data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidModelOutputError("AI response has no message content") from exc

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            ]
            if text_parts:
                return "".join(text_parts)

        raise InvalidModelOutputError("AI response message content is not text")

    def _parse_model_output(self, content: str) -> ModelExtractionResponse:
        try:
            raw = json.loads(content)
        except JSONDecodeError as exc:
            raise InvalidModelOutputError("AI response is not valid JSON") from exc

        try:
            return ModelExtractionResponse.model_validate(raw)
        except ValidationError as exc:
            raise InvalidModelOutputError(
                "AI response did not match the todo schema"
            ) from exc
