"""Thin wrapper around the OpenAI SDK, pointed at DeepSeek (OpenAI-compatible).

Every AI feature goes through `AIClient.complete_json`, so swapping the model or
provider is a configuration change.
"""

import asyncio
import logging
from typing import Any

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from pydantic import BaseModel, ValidationError

from app.core.exceptions import AIResponseError

logger = logging.getLogger(__name__)

# DeepSeek's current models "think" before answering by default, which can take minutes.
# Our tasks are short (extract, score, draft, call a tool), so answer directly.
NO_THINKING: dict[str, Any] = {"thinking": {"type": "disabled"}}
MAX_TOKENS = 4000  # a hard stop if the model rambles
# The SDK timeout is per read, and DeepSeek sends keep-alive bytes while it works,
# so a stuck request could run for minutes. This caps the whole call.
REQUEST_DEADLINE_SECONDS = 90.0


class AIClient:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=1)
        self.model = model

    async def complete_json[T: BaseModel](
        self, *, system: str, user: str, schema: type[T], temperature: float = 0.3
    ) -> T:
        """Ask the model for a JSON object and validate it against `schema`."""
        response = await self._create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )

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
        response = await self._create(messages=messages, tools=tools, temperature=temperature)
        return response.choices[0].message

    async def _create(self, **params: Any) -> ChatCompletion:
        """Call the chat completions API; provider errors and timeouts become a 502."""
        try:
            async with asyncio.timeout(REQUEST_DEADLINE_SECONDS):
                return await self._client.chat.completions.create(
                    model=self.model, max_tokens=MAX_TOKENS, extra_body=NO_THINKING, **params
                )
        except APIError as exc:
            logger.warning("AI provider error: %s", exc)
            raise AIResponseError("The AI provider request failed") from exc
        except TimeoutError as exc:
            logger.warning("AI provider timed out after %ss", REQUEST_DEADLINE_SECONDS)
            raise AIResponseError("The AI provider took too long to answer") from exc
