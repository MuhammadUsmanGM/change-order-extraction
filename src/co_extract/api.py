"""FastAPI application for Change-Order Extraction."""

import logging
import time
import uuid
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from co_extract.config import get_settings
from co_extract.ingest import (
    CorruptFileError,
    EmptyDocumentError,
    IngestError,
    UnsupportedFileError,
)
from co_extract.pipeline import PipelineResult, run_pipeline
from co_extract.providers.base import (
    ProviderError,
    ProviderTimeoutError,
)

logger = logging.getLogger("co_extract.api")

app = FastAPI(
    title="Change-Order Extraction API",
    description="Extract structured change order fields from messy PDFs and text into validated JSON.",
    version="0.1.0",
)


class TextExtractRequest(BaseModel):
    """Request model for direct text extraction."""

    text: str = Field(description="Raw text content of the change order")
    provider: Literal["claude", "gemini", "both"] = Field(
        default="claude", description="Provider adapter to execute"
    )
    mock: bool | None = Field(default=None, description="Override mock mode")


class ExtractResponse(PipelineResult):
    """Enriched response for API clients."""

    request_id: str = Field(description="Unique request tracing identifier")


@app.exception_handler(UnsupportedFileError)
@app.exception_handler(CorruptFileError)
@app.exception_handler(EmptyDocumentError)
async def handle_ingest_bad_request(_request: Request, exc: IngestError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error_type": exc.__class__.__name__},
    )


@app.exception_handler(ProviderTimeoutError)
async def handle_provider_timeout(_request: Request, exc: ProviderTimeoutError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={"detail": str(exc), "error_type": "ProviderTimeoutError"},
    )


@app.exception_handler(ProviderError)
async def handle_provider_error(_request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": str(exc), "error_type": exc.__class__.__name__},
    )


@app.get("/health", tags=["Status"])
async def get_health() -> dict[str, Any]:
    """Check service health and provider configuration status without revealing keys."""
    settings = get_settings()
    return {
        "status": "healthy",
        "mock_mode": settings.mock_mode,
        "claude_configured": bool(settings.anthropic_api_key),
        "gemini_configured": bool(settings.gemini_api_key),
    }


@app.get("/providers", tags=["Status"])
async def get_providers() -> dict[str, Any]:
    """Return available providers and their configured model identifiers."""
    settings = get_settings()
    return {
        "available_providers": ["claude", "gemini", "both"],
        "models": {
            "claude": settings.claude_model,
            "gemini": settings.gemini_model,
        },
    }


@app.post(
    "/extract",
    response_model=ExtractResponse,
    tags=["Extraction"],
    summary="Extract structured change order from uploaded file or text",
)
async def extract_change_order(
    request: Request,
    file: UploadFile | None = File(None, description="PDF or text file upload"),
    provider: Literal["claude", "gemini", "both"] = Form(
        "claude", description="Provider adapter to execute"
    ),
    mock: bool | None = Form(None, description="Override mock mode"),
) -> ExtractResponse:
    """Extract and validate change order details from an uploaded file or JSON body."""
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    source: bytes | str
    filename: str | None = None

    # Check for file upload
    if file is not None and file.filename:
        filename = file.filename
        content = await file.read()
        max_bytes = settings.max_upload_mb * 1024 * 1024

        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Uploaded file size ({len(content)} bytes) exceeds limit of {settings.max_upload_mb} MB.",
            )
        source = content
    else:
        # Check for JSON request body
        try:
            body = await request.json()
            extract_req = TextExtractRequest.model_validate(body)
            source = extract_req.text
            provider = extract_req.provider
            if extract_req.mock is not None:
                mock = extract_req.mock
            filename = "json_input.txt"
        except Exception as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Either a file upload or a valid JSON body with 'text' is required: {err}",
            ) from err

    result = run_pipeline(
        source=source,
        filename=filename,
        provider=provider,
        mock=mock,
    )

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Request %s completed in %.2f ms (providers=%s, ocr=%s)",
        request_id,
        elapsed_ms,
        result.providers_used,
        result.ocr_used,
    )

    return ExtractResponse(
        request_id=request_id,
        **result.model_dump(),
    )
