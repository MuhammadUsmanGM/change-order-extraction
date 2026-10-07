"""Gemini extraction adapter using google-genai SDK with JSON response schema."""

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
    RawExtraction,
)
from co_extract.schema import ChangeOrder


class GeminiExtractor:
    """Extractor adapter for Google Gemini models."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.max_retries = max_retries
        self.name = "gemini"

    def _get_client(self) -> Any:
        if not self.api_key:
            raise ProviderAuthError(
                "Gemini API key is not set. Please provide GEMINI_API_KEY in environment or .env"
            )
        try:
            from google import genai  # type: ignore[import-not-found]

            return genai.Client(api_key=self.api_key)
        except ImportError as err:
            raise ProviderError("google-genai package is not installed.") from err

    def _execute_with_backoff(self, client: Any, contents: str | list[Any]) -> Any:
        """Call Gemini API with exponential backoff on 429 and 5xx."""
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ChangeOrder,
        )

        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                return response
            except errors.ClientError as err:
                code = getattr(err, "code", None)
                msg = str(err).lower()
                if code == 401 or "api key" in msg or "permission" in msg:
                    raise ProviderAuthError(f"Gemini authentication failed: {err}") from err
                if code == 429 or "quota" in msg or "resource exhausted" in msg:
                    if attempt == self.max_retries - 1:
                        raise ProviderRateLimitError(f"Gemini rate limit exceeded: {err}") from err
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(f"Gemini client error: {err}") from err
            except errors.ServerError as err:
                if attempt == self.max_retries - 1:
                    raise ProviderError(f"Gemini server error: {err}") from err
                time.sleep(delay)
                delay *= 2
            except errors.APIError as err:
                code = getattr(err, "code", None)
                if code == 429 and attempt < self.max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(f"Gemini API error: {err}") from err
            except Exception as err:
                raise ProviderError(f"Unexpected error communicating with Gemini: {err}") from err

    def extract(self, doc: Document) -> RawExtraction:
        """Extract ChangeOrder using Gemini structured JSON generation with repair retry."""
        client = self._get_client()
        prompt = build_extraction_user_prompt(doc.text)

        start_time = time.perf_counter()
        response = self._execute_with_backoff(client, prompt)
        latency_ms = (time.perf_counter() - start_time) * 1000

        text_content = getattr(response, "text", "") or ""
        if not text_content.strip():
            raise ProviderBadOutputError("Gemini returned empty response text.")

        # Parse output with 1 repair retry on validation failure
        try:
            change_order = ChangeOrder.model_validate_json(text_content)
        except Exception as validation_err:
            repair_prompt = (
                f"{prompt}\n\n"
                f"Previous output was:\n{text_content}\n\n"
                f"Validation error occurred: {validation_err}\n"
                f"Please correct the JSON output according to the schema."
            )
            repair_response = self._execute_with_backoff(client, repair_prompt)
            repair_text = getattr(repair_response, "text", "") or ""
            if not repair_text.strip():
                raise ProviderBadOutputError(
                    f"Gemini repair response was empty: {validation_err}"
                ) from validation_err
            try:
                change_order = ChangeOrder.model_validate_json(repair_text)
                text_content = repair_text
            except Exception as final_err:
                raise ProviderBadOutputError(
                    f"Gemini output invalid after repair retry: {final_err}"
                ) from final_err

        # Extract self-reported model confidences
        model_confidence: dict[str, float] = {}
        for field_name, val in change_order:
            if hasattr(val, "confidence"):
                model_confidence[field_name] = val.confidence

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        return RawExtraction(
            change_order=change_order,
            model_confidence=model_confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_response=text_content,
            provider_name=self.name,
            model_name=self.model,
        )


# Verify protocol conformance
_: Extractor = GeminiExtractor()
