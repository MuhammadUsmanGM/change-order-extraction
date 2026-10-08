"""Unit tests for the Typer CLI application."""

import json
from pathlib import Path

from typer.testing import CliRunner

from co_extract.cli import app
from co_extract.providers.base import RawExtraction
from co_extract.providers.mock import save_fixture
from co_extract.schema import ChangeOrder, ExtractedField

runner = CliRunner()


def test_cli_run_mock_success(tmp_path: Path):
    """Verify co-extract run command in mock mode."""
    doc_file = tmp_path / "test_doc.txt"
    doc_text = "Change Order CO-500 Scope adjustment"
    doc_file.write_text(doc_text, encoding="utf-8")

    from co_extract.ingest import ingest_document

    doc = ingest_document(doc_file)

    co = ChangeOrder(co_number=ExtractedField.from_value("CO-500", 0.95, "CO-500"))
    raw = RawExtraction(
        change_order=co,
        provider_name="claude",
        model_name="claude-mock",
    )
    # Save fixture in default fixture dir
    from co_extract.providers.mock import DEFAULT_FIXTURES_DIR

    save_fixture(raw, doc.text, fixtures_dir=DEFAULT_FIXTURES_DIR)

    out_file = tmp_path / "output.json"
    result = runner.invoke(
        app,
        ["run", str(doc_file), "--provider", "claude", "--mock", "--out", str(out_file)],
    )

    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["change_order"]["co_number"]["value"] == "CO-500"


def test_cli_run_invalid_provider(tmp_path: Path):
    """Verify invalid provider produces error and non-zero exit code."""
    doc_file = tmp_path / "doc.txt"
    doc_file.write_text("Dummy text", encoding="utf-8")

    result = runner.invoke(app, ["run", str(doc_file), "--provider", "invalid_provider"])
    assert result.exit_code != 0
    assert "Invalid provider" in result.output


def test_cli_run_missing_file():
    """Verify missing file argument fails cleanly."""
    result = runner.invoke(app, ["run", "non_existent_file.pdf"])
    assert result.exit_code != 0


def test_cli_eval_command():
    """Verify eval command executes cleanly."""
    result = runner.invoke(app, ["eval", "--provider", "claude", "--mock"])
    assert result.exit_code == 0
    assert "evaluation benchmark" in result.output.lower()
    assert "field accuracy" in result.output.lower()
