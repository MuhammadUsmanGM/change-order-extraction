"""Claude extraction adapter using Anthropic SDK with forced tool use."""

import time
from typing import Any

from co_extract.config import get_settings
from co_extract.ingest import Document
from co_extract.prompts import SYSTEM_PROMPT, build_extraction_user_prompt
from co_extract.providers.base import (
    Extractor,
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    RawExtraction,
)
from co_extract.schema import ChangeOrder, get_change_order_json_schema

TOOL_NAME = "extract_change_order"


def _clean_schema_for_anthropic(schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure JSON Schema meets Anthropic tool definition requirements."""
    cleaned = dict(schema)
    cleaned.pop("title", None)
    return cleaned


class ClaudeExtractor:
    """Extractor adapter for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.claude_model
        self.max_retries = max_retries
        self.name = "claude"

    def _get_client(self) -> Any:
        if not self.api_key:
            raise ProviderAuthError(
                "Anthropic API key is not set. Please provide ANTHROPIC_API_KEY in environment or .env"
            )
        try:
            import anthropic  # type: ignore[import-not-found]

            return anthropic.Anthropic(api_key=self.api_key)
        except ImportError as err:
            raise ProviderError("anthropic package is not installed.") from err

    def _execute_with_backoff(
        self, client: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any:
        """Call Claude API with exponential backoff on 429 and 5xx."""
        import anthropic

        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                response = client.messages.create(
                    model=self.model,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                    max_tokens=4096,
                )
                return response
            except anthropic.AuthenticationError as err:
                raise ProviderAuthError(f"Anthropic authentication failed: {err}") from err
            except anthropic.RateLimitError as err:
                if attempt == self.max_retries - 1:
                    raise ProviderRateLimitError(f"Anthropic rate limit exceeded: {err}") from err
                time.sleep(delay)
                delay *= 2
            except anthropic.APITimeoutError as err:
                if attempt == self.max_retries - 1:
                    raise ProviderTimeoutError(f"Anthropic request timed out: {err}") from err
                time.sleep(delay)
                delay *= 2
            except anthropic.APIStatusError as err:
                if err.status_code and err.status_code >= 500 and attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(f"Anthropic API error: {err}") from err
            except Exception as err:
                raise ProviderError(
                    f"Unexpected error communicating with Anthropic: {err}"
                ) from err

    def extract(self, doc: Document) -> RawExtraction:
        """Extract ChangeOrder using Claude tool calling with repair retry."""
        client = self._get_client()

        tools = [
            {
                "name": TOOL_NAME,
                "description": "Extract structured change order fields from the document.",
                "input_schema": _clean_schema_for_anthropic(get_change_order_json_schema()),
            }
        ]

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_extraction_user_prompt(doc.text)}
        ]

        start_time = time.perf_counter()
        response = self._execute_with_backoff(client, messages, tools)
        latency_ms = (time.perf_counter() - start_time) * 1000

        tool_input: dict[str, Any] | None = None
        for block in response.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == TOOL_NAME
            ):
                tool_input = getattr(block, "input", None)
                break

        if not tool_input or not isinstance(tool_input, dict):
            raise ProviderBadOutputError(
                f"Claude did not invoke '{TOOL_NAME}' tool or returned invalid format."
            )

        # Attempt Pydantic validation with 1 repair retry
        try:
            change_order = ChangeOrder.model_validate(tool_input)
        except Exception as validation_err:
            # Repair retry: feed error back to Claude
            repair_messages = list(messages)
            repair_messages.append({"role": "assistant", "content": response.content})
            repair_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The output failed validation with error: {validation_err}.\n"
                        f"Please fix the schema issues and re-invoke '{TOOL_NAME}'."
                    ),
                }
            )
            repair_response = self._execute_with_backoff(client, repair_messages, tools)
            tool_input = None
            for block in repair_response.content:
                if (
                    getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == TOOL_NAME
                ):
                    tool_input = getattr(block, "input", None)
                    break
            if not tool_input:
                raise ProviderBadOutputError(
                    f"Claude repair retry failed to produce tool use: {validation_err}"
                ) from validation_err
            try:
                change_order = ChangeOrder.model_validate(tool_input)
            except Exception as final_err:
                raise ProviderBadOutputError(
                    f"Claude output still invalid after repair retry: {final_err}"
                ) from final_err

        # Extract self-reported model confidences
        model_confidence: dict[str, float] = {}
        for field_name, val in change_order:
            if hasattr(val, "confidence"):
                model_confidence[field_name] = val.confidence

        input_tokens = getattr(getattr(response, "usage", None), "input_tokens", 0)
        output_tokens = getattr(getattr(response, "usage", None), "output_tokens", 0)

        return RawExtraction(
            change_order=change_order,
            model_confidence=model_confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_response=tool_input,
            provider_name=self.name,
            model_name=self.model,
        )


# Verify protocol conformance
_: Extractor = ClaudeExtractor()
