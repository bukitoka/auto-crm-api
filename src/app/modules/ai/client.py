"""Thin wrapper around the OpenAI SDK, pointed at DeepSeek (OpenAI-compatible).

Every AI feature goes through `AIClient.complete_json`, so swapping the model or
provider is a configuration change.
"""

import logging
from typing import Any

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel, ValidationError

from app.core.exceptions import AIResponseError

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        self.model = model

    async def complete_json[T: BaseModel](
        self, *, system: str, user: str, schema: type[T], temperature: float = 0.3
    ) -> T:
        """Ask the model for a JSON object and validate it against `schema`."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
        except APIError as exc:
            logger.warning("AI provider error: %s", exc)
            raise AIResponseError("The AI provider request failed") from exc

        content = response.choices[0].message.content or ""
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            logger.warning("Invalid AI output for %s: %s", schema.__name__, content)
            raise AIResponseError() from exc

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
    ) -> ChatCompletionMessage:
        """One chat turn with function calling. The reply may contain `tool_calls` to run."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # ty: ignore[invalid-argument-type]
                tools=tools,  # ty: ignore[invalid-argument-type]
                temperature=temperature,
            )
        except APIError as exc:
            logger.warning("AI provider error: %s", exc)
            raise AIResponseError("The AI provider request failed") from exc
        return response.choices[0].message
