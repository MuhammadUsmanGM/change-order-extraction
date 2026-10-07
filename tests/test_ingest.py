"""Unit tests for the ingestion module."""

from pathlib import Path

import fitz
import pytest

from co_extract.ingest import (
    CorruptFileError,
    Document,
    EmptyDocumentError,
    UnsupportedFileError,
    ingest_document,
)


def test_ingest_raw_text():
    """Verify raw string ingestion."""
    text = "Change Order 101\nProject: Sky High\nTotal: $12,000"
    doc = ingest_document(text)
    assert isinstance(doc, Document)
    assert "--- PAGE 1 ---" in doc.text
    assert "Change Order 101" in doc.text
    assert doc.ocr_used is False
    assert doc.metadata["type"] == "text"


def test_ingest_text_file(tmp_path: Path):
    """Verify text file ingestion from disk."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Change Order Document\nScope of work: painting", encoding="utf-8")
    doc = ingest_document(file_path)
    assert "Scope of work: painting" in doc.text
    assert doc.metadata["filename"] == "sample.txt"


def test_empty_text_error():
    """Verify empty text raises EmptyDocumentError."""
    with pytest.raises(EmptyDocumentError):
        ingest_document("   \n  \t  ")


def test_unsupported_file_extension(tmp_path: Path):
    """Verify unsupported extensions raise UnsupportedFileError."""
    file_path = tmp_path / "document.docx"
    file_path.write_bytes(b"dummy docx bytes")
    with pytest.raises(UnsupportedFileError):
        ingest_document(file_path)


def test_corrupt_pdf_data():
    """Verify malformed PDF bytes raise CorruptFileError."""
    corrupt_data = b"%PDF-1.4 corrupt invalid binary content"
    with pytest.raises(CorruptFileError):
        ingest_document(corrupt_data, filename="corrupt.pdf")


def test_multi_page_pdf_ingestion():
    """Verify PDF creation, multi-page markers, and content extraction."""
    # Create an in-memory PDF with PyMuPDF
    pdf = fitz.open()
    p1 = pdf.new_page()
    p1.insert_text((50, 100), "Change Order # 001 - Page One Header and Details")
    p2 = pdf.new_page()
    p2.insert_text((50, 100), "Change Order # 001 - Page Two Signatures and Approvals")

    pdf_bytes = pdf.tobytes()
    pdf.close()

    doc = ingest_document(pdf_bytes, filename="multipage.pdf")
    assert "--- PAGE 1 ---" in doc.text
    assert "--- PAGE 2 ---" in doc.text
    assert "Page One Header" in doc.text
    assert "Signatures and Approvals" in doc.text
    assert len(doc.pages) == 2
    assert doc.metadata["page_count"] == 2


def test_scan_detection_and_ocr_warning():
    """Verify that a page with fewer characters than threshold triggers scan logic and warning."""
    pdf = fitz.open()
    page = pdf.new_page()
    # Insert tiny text below threshold
    page.insert_text((50, 100), "Hi")  # 2 characters < CHARS_PER_PAGE_THRESHOLD
    pdf_bytes = pdf.tobytes()
    pdf.close()

    doc = ingest_document(pdf_bytes, filename="scanned_stub.pdf")
    # Low chars will either run OCR or log an OCR warning if tesseract binary is absent
    assert len(doc.warnings) > 0 or doc.ocr_used is True
