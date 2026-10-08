"""Tests verifying synthetic dataset generation and schema validity."""

from pathlib import Path

from co_extract.ingest import ingest_document
from co_extract.schema import ChangeOrder

DOCS_DIR = Path("data/docs")
TRUTH_DIR = Path("data/truth")


def test_all_12_documents_exist():
    """Verify that all 12 synthetic documents exist in data/docs."""
    expected_docs = [
        "doc_01_clean_standard.pdf",
        "doc_02_table_heavy.pdf",
        "doc_03_email_plain_text.txt",
        "doc_04_scanned_noisy.pdf",
        "doc_05_multipage_split_table.pdf",
        "doc_06_superseded_revisions.pdf",
        "doc_07_conflicting_totals.pdf",
        "doc_08_sparse_missing_fields.pdf",
        "doc_09_deductive_negative.pdf",
        "doc_10_european_locale.pdf",
        "doc_11_annotated_amendment.pdf",
        "doc_12_prompt_injection.pdf",
    ]
    for doc_name in expected_docs:
        doc_path = DOCS_DIR / doc_name
        assert doc_path.exists(), f"Missing dataset document: {doc_name}"
        assert doc_path.stat().st_size > 0


def test_all_12_truth_files_parse():
    """Verify that all 12 truth JSON files parse into valid ChangeOrder instances."""
    for idx in range(1, 13):
        truth_file = TRUTH_DIR / f"truth_{idx:02d}.json"
        assert truth_file.exists(), f"Missing ground truth file: {truth_file}"
        raw_json = truth_file.read_text(encoding="utf-8")
        co = ChangeOrder.model_validate_json(raw_json)
        assert isinstance(co, ChangeOrder)
        assert co.co_number.value is not None


def test_all_12_documents_ingest_without_error():
    """Verify that ingest_document can parse every document in the dataset."""
    for idx in range(1, 13):
        matches = list(DOCS_DIR.glob(f"doc_{idx:02d}_*.*"))
        assert len(matches) == 1, f"Expected exactly 1 document for case {idx}"
        doc_path = matches[0]
        doc = ingest_document(doc_path)
        assert len(doc.text) > 0
        assert "--- PAGE 1 ---" in doc.text
