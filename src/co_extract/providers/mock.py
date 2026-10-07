"""Mock provider supporting recording and replaying extractions offline."""

import hashlib
import json
from pathlib import Path
from typing import Any

from co_extract.ingest import Document
from co_extract.prompts import PROMPT_VERSION
from co_extract.providers.base import Extractor, ProviderBadOutputError, RawExtraction
from co_extract.schema import ChangeOrder

DEFAULT_FIXTURES_DIR = Path("data/fixtures")


def compute_fixture_hash(
    document_text: str,
    provider_name: str,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Generate deterministic SHA-256 hash for document text, provider, and prompt version."""
    key = f"{document_text.strip()}:{provider_name}:{prompt_version}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def save_fixture(
    extraction: RawExtraction,
    document_text: str,
    fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
    prompt_version: str = PROMPT_VERSION,
) -> Path:
    """Save a RawExtraction to a JSON fixture file on disk."""
    fixtures_path = Path(fixtures_dir)
    fixtures_path.mkdir(parents=True, exist_ok=True)

    fixture_hash = compute_fixture_hash(
        document_text=document_text,
        provider_name=extraction.provider_name,
        prompt_version=prompt_version,
    )
    fixture_file = fixtures_path / f"{fixture_hash}.json"

    payload: dict[str, Any] = {
        "hash": fixture_hash,
        "provider_name": extraction.provider_name,
        "model_name": extraction.model_name,
        "prompt_version": prompt_version,
        "input_tokens": extraction.input_tokens,
        "output_tokens": extraction.output_tokens,
        "latency_ms": extraction.latency_ms,
        "model_confidence": extraction.model_confidence,
        "change_order": extraction.change_order.model_dump(mode="json"),
        "raw_response": extraction.raw_response,
    }

    fixture_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return fixture_file


def load_fixture(
    document_text: str,
    provider_name: str,
    fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
    prompt_version: str = PROMPT_VERSION,
) -> RawExtraction:
    """Load a pre-recorded RawExtraction from disk matching the fixture hash."""
    fixtures_path = Path(fixtures_dir)
    fixture_hash = compute_fixture_hash(
        document_text=document_text,
        provider_name=provider_name,
        prompt_version=prompt_version,
    )
    fixture_file = fixtures_path / f"{fixture_hash}.json"

    if not fixture_file.is_file():
        raise ProviderBadOutputError(
            f"Mock fixture not found for hash '{fixture_hash}' in '{fixtures_path}'. "
            f"Run with a live provider and --record to create offline fixtures."
        )

    try:
        data = json.loads(fixture_file.read_text(encoding="utf-8"))
        co = ChangeOrder.model_validate(data["change_order"])
        return RawExtraction(
            change_order=co,
            model_confidence=data.get("model_confidence", {}),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            latency_ms=data.get("latency_ms", 5.0),
            raw_response=data.get("raw_response"),
            provider_name=data.get("provider_name", provider_name),
            model_name=data.get("model_name", "mock-replay"),
        )
    except Exception as err:
        raise ProviderBadOutputError(
            f"Failed to parse mock fixture file '{fixture_file}': {err}"
        ) from err


class MockExtractor:
    """Mock extractor for offline testing and replay."""

    def __init__(
        self,
        target_provider_name: str = "claude",
        fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
        prompt_version: str = PROMPT_VERSION,
        fallback_data: ChangeOrder | None = None,
    ):
        self.name = f"mock-{target_provider_name}"
        self.target_provider_name = target_provider_name
        self.fixtures_dir = Path(fixtures_dir)
        self.prompt_version = prompt_version
        self.fallback_data = fallback_data

    def extract(self, doc: Document) -> RawExtraction:
        """Extract by replaying a saved fixture from disk, or using fallback data if provided."""
        try:
            return load_fixture(
                document_text=doc.text,
                provider_name=self.target_provider_name,
                fixtures_dir=self.fixtures_dir,
                prompt_version=self.prompt_version,
            )
        except ProviderBadOutputError:
            if self.fallback_data is not None:
                return RawExtraction(
                    change_order=self.fallback_data,
                    model_confidence={},
                    input_tokens=100,
                    output_tokens=50,
                    latency_ms=10.0,
                    raw_response={"mock": True},
                    provider_name=self.name,
                    model_name="mock-fallback",
                )
            raise


# Verify protocol conformance
_: Extractor = MockExtractor()
