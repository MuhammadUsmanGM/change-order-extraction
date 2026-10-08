"""Ingestion module for PDFs, text files, and scanned documents."""

from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Constants
CHARS_PER_PAGE_THRESHOLD = 50


class IngestError(Exception):
    """Base exception for ingestion errors."""


class UnsupportedFileError(IngestError):
    """Raised when an unsupported file format is provided."""


class CorruptFileError(IngestError):
    """Raised when a document cannot be parsed or opened."""


class EmptyDocumentError(IngestError):
    """Raised when an input document has zero text/content."""


class Document(BaseModel):
    """Normalized ingested document."""

    text: str = Field(description="Full text extracted across all pages with page markers")
    pages: list[str] = Field(default_factory=list, description="Text content per page")
    ocr_used: bool = Field(default=False, description="Whether OCR was performed on any page")
    ocr_pages: list[int] = Field(
        default_factory=list, description="1-indexed page numbers where OCR was applied"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Warnings encountered during ingestion"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadata such as filename, page count, char count"
    )


def _format_table_to_pipe_delimited(table: Any) -> str:
    """Format PyMuPDF Table object into pipe-delimited markdown table."""
    try:
        rows = table.extract()
        if not rows:
            return ""
        lines: list[str] = []
        for r_idx, row in enumerate(rows):
            # Clean cells: replace internal newlines and strip whitespace
            clean_cells = [str(c or "").replace("\n", " ").strip() for c in row]
            line = "| " + " | ".join(clean_cells) + " |"
            lines.append(line)
            if r_idx == 0:
                # Add header separator
                sep = "| " + " | ".join("---" for _ in clean_cells) + " |"
                lines.append(sep)
        return "\n".join(lines)
    except Exception:
        return ""


def _try_ocr_page(page: Any, page_num: int) -> tuple[str | None, str | None]:
    """Attempt pytesseract OCR on a PyMuPDF page rendered as a pixmap."""
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        # Render page to image
        pix = page.get_pixmap(dpi=200)
        img = Image.open(BytesIO(pix.tobytes("png")))
        ocr_text = pytesseract.image_to_string(img)
        if ocr_text and ocr_text.strip():
            return ocr_text.strip(), None
        return None, f"Page {page_num}: OCR ran but produced no characters."
    except Exception as exc:
        return (
            None,
            f"Page {page_num}: OCR unavailable or failed ({exc.__class__.__name__}: {exc}).",
        )


def _ingest_pdf(data: bytes, filename: str) -> Document:
    """Parse PDF data using PyMuPDF (fitz) with table extraction and OCR fallback."""
    try:
        import fitz  # PyMuPDF # type: ignore[import-not-found]
    except ImportError as err:
        raise IngestError("PyMuPDF (fitz) is required for PDF ingestion.") from err

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as err:
        raise CorruptFileError(f"Failed to open PDF document: {err}") from err

    if len(doc) == 0:
        raise EmptyDocumentError(f"PDF document '{filename}' contains 0 pages.")

    pages_text: list[str] = []
    ocr_pages: list[int] = []
    warnings: list[str] = []
    ocr_used = False

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1

        # Extract text directly
        raw_text = page.get_text()

        # Check for tables using PyMuPDF table finder
        table_text = ""
        try:
            tables = page.find_tables()
            if tables and len(tables.tables) > 0:
                formatted_tables = [_format_table_to_pipe_delimited(tbl) for tbl in tables.tables]
                table_text = "\n\n".join(t for t in formatted_tables if t)
        except Exception as table_err:
            warnings.append(f"Page {page_num}: Table extraction failed ({table_err}).")

        # Combine text and table representation if present
        combined_page_text = raw_text.strip()
        if table_text:
            combined_page_text = (
                f"{combined_page_text}\n\n[Extracted Tables]:\n{table_text}".strip()
            )

        # Check if page looks like a scan (few or zero text characters)
        char_count = len(raw_text.strip())
        if char_count < CHARS_PER_PAGE_THRESHOLD:
            ocr_text, ocr_warning = _try_ocr_page(page, page_num)
            if ocr_text:
                combined_page_text = ocr_text
                ocr_used = True
                ocr_pages.append(page_num)
            if ocr_warning:
                warnings.append(ocr_warning)

        pages_text.append(combined_page_text)

    # Check total extracted content
    total_chars = sum(len(p.strip()) for p in pages_text)
    if total_chars == 0:
        # Check if pages contain images (scanned document)
        has_images = any(len(p.get_images()) > 0 for p in doc)
        if has_images:
            warnings.append("Scanned document with images detected, but no OCR text was extracted.")
            pages_text = [
                "[Scanned page: OCR unavailable or produced no text]" for _ in range(len(doc))
            ]
            total_chars = sum(len(p) for p in pages_text)
        else:
            raise EmptyDocumentError(f"PDF document '{filename}' contains no extractable text.")

    # Build full document text with page markers
    full_text_parts: list[str] = []
    for idx, p_text in enumerate(pages_text):
        full_text_parts.append(f"--- PAGE {idx + 1} ---\n{p_text}")
    full_text = "\n\n".join(full_text_parts)

    return Document(
        text=full_text,
        pages=pages_text,
        ocr_used=ocr_used,
        ocr_pages=ocr_pages,
        warnings=warnings,
        metadata={
            "filename": filename,
            "page_count": len(doc),
            "char_count": total_chars,
            "type": "pdf",
        },
    )


def _ingest_text(text_content: str, filename: str) -> Document:
    """Ingest plain text or markdown content."""
    clean_text = text_content.strip()
    if not clean_text:
        raise EmptyDocumentError(f"Document '{filename}' is empty.")

    # Split by form-feed character if present, else single page
    raw_pages = clean_text.split("\x0c") if "\x0c" in clean_text else [clean_text]
    pages = [p.strip() for p in raw_pages if p.strip()]

    full_text_parts = [f"--- PAGE {idx + 1} ---\n{page}" for idx, page in enumerate(pages)]
    full_text = "\n\n".join(full_text_parts)

    return Document(
        text=full_text,
        pages=pages,
        ocr_used=False,
        ocr_pages=[],
        warnings=[],
        metadata={
            "filename": filename,
            "page_count": len(pages),
            "char_count": len(clean_text),
            "type": "text",
        },
    )


def ingest_document(
    source: str | Path | bytes,
    filename: str | None = None,
) -> Document:
    """Ingest a document from a file path, raw bytes, or raw string.

    Args:
        source: File path (str/Path), raw bytes, or raw plain text string.
        filename: Optional filename hint when source is bytes.

    Returns:
        Document instance with extracted text, page markers, and metadata.
    """
    # 1. Handle Path or str pointing to existing file
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_file():
            fname = filename or path.name
            suffix = path.suffix.lower()
            try:
                content = path.read_bytes()
            except Exception as err:
                raise CorruptFileError(f"Failed to read file '{path}': {err}") from err

            if suffix == ".pdf":
                return _ingest_pdf(content, fname)
            elif suffix in [".txt", ".md", ".text"]:
                try:
                    text_str = content.decode("utf-8")
                except UnicodeDecodeError:
                    text_str = content.decode("latin-1", errors="replace")
                return _ingest_text(text_str, fname)
            else:
                raise UnsupportedFileError(
                    f"Unsupported file format '{suffix}'. Supported: .pdf, .txt, .md"
                )

        # If source is a string but not an existing file on disk, treat as raw text content
        if isinstance(source, str):
            return _ingest_text(source, filename or "raw_text_input")

    # 2. Handle raw bytes
    if isinstance(source, bytes):
        fname = filename or "uploaded_document"
        if fname.lower().endswith(".pdf") or source.startswith(b"%PDF-"):
            return _ingest_pdf(source, fname)
        else:
            try:
                text_str = source.decode("utf-8")
            except UnicodeDecodeError:
                text_str = source.decode("latin-1", errors="replace")
            return _ingest_text(text_str, fname)

    raise UnsupportedFileError(f"Unsupported source type: {type(source).__name__}")
