# Change-Order Extraction Pipeline

Extract structured fields from messy change-order PDFs and text files into validated JSON with confidence scores.

This project was built for the Sledge AI Engineer technical evaluation. It runs completely locally with **no external database** and includes a **full offline mock mode**, so you can test and evaluate everything immediately without needing any API keys.

---

## Quick Start (Run in under 2 minutes without API keys)

### 1. Install

```bash
git clone https://github.com/MuhammadUsmanGM/change-order-extraction.git
cd change-order-extraction
pip install -e ".[dev,pipeline]"
```

### 2. Run an Extraction Offline (Mock Mode)

Extract a standard change-order PDF:

```bash
co-extract run data/docs/doc_01_clean_standard.pdf --mock
```

*(Note: You can also use `python -m co_extract.cli run data/docs/doc_01_clean_standard.pdf --mock` if CLI binaries are not on your system PATH)*

To save the output to a JSON file:

```bash
co-extract run data/docs/doc_01_clean_standard.pdf --mock --out result.json
```

### 3. Run the Evaluation Benchmark

Run the full evaluation across all 12 edge-case documents:

```bash
co-extract eval --mock
```

This will run all 12 documents and print the complete benchmark results table in your terminal.

---

## Live Extraction (With Real API Keys)

To run extractions against live Claude or Gemini models:

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and paste your API keys:
   ```env
   ANTHROPIC_API_KEY=your_key_here
   GEMINI_API_KEY=your_key_here
   ```
3. Run extraction using both providers with cross-provider agreement scoring:
   ```bash
   co-extract run data/docs/doc_01_clean_standard.pdf --provider both
   ```
   *(Or choose a single provider: `--provider claude` or `--provider gemini`)*

---

## Running the REST API

### Local Server

Start the FastAPI server:

```bash
uvicorn co_extract.api:app --reload --port 8000
```

Open the interactive API documentation in your browser:
**[http://localhost:8000/docs](http://localhost:8000/docs)**

### Example API Requests

**Extract from a text snippet (JSON):**
```bash
curl -X POST "http://localhost:8000/extract" \
  -H "Content-Type: application/json" \
  -d '{"text": "Change Order CO-101. Total amount is $12,500.00.", "mock": true}'
```

**Extract from an uploaded PDF file:**
```bash
curl -X POST "http://localhost:8000/extract" \
  -F "file=@data/docs/doc_01_clean_standard.pdf" \
  -F "mock=true"
```

**Health check:**
```bash
curl "http://localhost:8000/health"
```

---

## Running with Docker

Build and start the container:

```bash
docker build -t change-order-extractor .
docker run -p 8000:8000 change-order-extractor
```

Access the API docs at `http://localhost:8000/docs`.

---

## Running Tests

All 68 unit, integration, and security tests run offline with zero API keys:

```bash
make check
```

Or run pytest directly:

```bash
pytest
```

---

## How It Works

```
File or Text Input
       │
       ▼
1. INGESTION  ───► Extracts text, preserves page numbers, formats tables, and handles OCR.
       │
       ▼
2. EXTRACTION ───► Claude or Gemini extracts fields into structured JSON schema (or Mock replay).
       │
       ▼
3. VALIDATION ───► 10 deterministic checks (V1 to V10) verify math, dates, and grounding.
       │
       ▼
4. CONFIDENCE ───► Calculates a 0.0 to 1.0 confidence score per field and assigns a review band.
       │
       ▼
Validated JSON Output (values, confidence, verbatim quotes, and defect flags)
```

For the complete technical breakdown, benchmark table, and failure modes analysis, please see **[WRITEUP.md](WRITEUP.md)**.
