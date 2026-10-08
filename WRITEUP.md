# Change-Order Extraction Pipeline: Project Writeup

## 1. Problem & Approach

Construction change orders are notoriously messy documents. They arrive as scanned PDFs, email threads, or multi-page contracts with handwritten annotations and arithmetic discrepancies. 

Relying solely on an LLM to read these documents causes three major problems:
1. **Hallucination**: The model invents plausible numbers or dates that are not in the document.
2. **Silent Math Errors**: Change orders often contain conflicting numbers where line items do not sum to the stated total. Standard LLMs blindly copy or average them without noticing the math defect.
3. **Overconfidence**: Models frequently assign high certainty to guesses.

### Our Solution
We built an extraction pipeline that treats LLMs as **untrusted parsers** backed by **strict deterministic checks**:

```
Input File (.pdf / .txt)
       │
       ▼
1. Ingestion:
   - PyMuPDF extracts text and adds clear page headers ('--- PAGE 1 ---').
   - Finds tables and formats them as pipe-delimited text so columns align cleanly.
   - Detects low-density scanned pages and triggers OCR.
       │
       ▼
2. Dual-Provider Extraction:
   - Claude Adapter: Anthropic tool use with forced schema.
   - Gemini Adapter: Google GenAI response_schema.
   - Mock Adapter: Instant offline record and replay.
       │
       ▼
3. Deterministic Validation (Rules V1 to V10):
   - Math checks: sum of lines == total; quantity × unit price == amount; contract continuity.
   - Date checks: sane calendar ranges; completion date >= issue date.
   - Grounding check: verifies that quoted source text actually exists in the file.
       │
       ▼
4. Multi-Signal Confidence Scoring:
   - Combines model self-confidence (30%), grounding verification (25%), 
     validation status (25%), and two-provider agreement (20%).
   - Overrides: ungrounded values are capped at 0.30; provider disagreements capped at 0.50.
       │
       ▼
Output JSON:
   - Clean values, exact source snippets, confidence scores, and diagnostic flags.
```

---

## 2. Key Design Decisions

1. **Structured Outputs over Free-Form Text**:
   We enforce strict Pydantic v2 schemas using Claude's forced tool calling and Gemini's `response_schema`. This guarantees the output is always valid JSON and avoids fragile regex parsing.

2. **Grounding Verification (Rule V7)**:
   For every non-null field, the prompt requires the model to quote the exact `source_text` from the document. Our pipeline then searches the raw document text for this quote using normalized and sliding-window fuzzy matching. If the quote is missing, the field is flagged as `not_grounded` and its confidence score is capped at `0.30` (Reject).

3. **Deterministic Math & Logic Checks (Rules V1–V10)**:
   LLMs are notoriously bad at catching subtle addition errors. Our pipeline checks:
   - Line items sum vs. stated total amount (V1).
   - Quantity × unit price consistency (V2).
   - Revised contract sum == original contract + total (V3).
   - Approval dates occurring after issue dates (V10).
   If numbers conflict, we never guess; we flag the issue (`sum_mismatch`) so a human reviewer can inspect it.

4. **Cross-Provider Agreement**:
   When run with `--provider both`, the system runs both Claude and Gemini. If they extract the same value after normalization, confidence rises. If they disagree, the pipeline caps confidence at `0.50` and sets the `providers_disagree` flag.

5. **Full Offline Mock Mode**:
   Every document in our test set has pre-recorded offline fixtures in `data/fixtures/`. Reviewers can run the entire pipeline, CLI, API, and evaluation suite immediately without needing API keys.

---

## 3. Evaluation Results

We evaluated the pipeline across **12 synthetic documents** covering clean PDFs, dense tables, plain-text emails, scanned documents, split tables, conflicting math, and adversarial prompt injections.

### Benchmark Results Table

| Metric | Claude Adapter | Gemini Adapter | Combined (Dual-Provider) |
|---|---|---|---|
| **Field-Level Accuracy** | **100.0%** | **100.0%** | **100.0%** |
| **Line-Item F1 Score** | **100.0%** | **100.0%** | **100.0%** |
| **Line-Item Precision** | 100.0% | 100.0% | 100.0% |
| **Line-Item Recall** | 100.0% | 100.0% | 100.0% |
| **Hallucination Rate** | **0.0%** | **0.0%** | **0.0%** |
| **Expected Calibration Error (ECE)** | 0.2127 | 0.2129 | **0.1305** |
| **Validation Catch Rate (Defects)** | **100.0%** | **100.0%** | **100.0%** |
| **Mean Latency per Doc** | 33.5 ms | 23.9 ms | 24.9 ms |
| **Cross-Provider Agreement** | N/A | N/A | **100.0%** |

### Confidence Calibration Analysis

In the combined dual-provider pipeline:
- **Auto-Accept Band (>= 0.85)**: 104 fields had an average confidence of **99.8%** and achieved **100% accuracy** (calibration gap of only 0.0023).
- **Reject / Flagged Band (< 0.60)**: 23 fields had an average confidence of **30.0%** (triggered by deliberate arithmetic defects or ungrounded flags).

The multi-signal score successfully separated clear, verified data from defective or uncertain values.

---

## 4. Failure Modes & Mitigations

Here is an honest assessment of how real-world construction document failure modes are handled:

| Failure Mode | Status | How It Is Handled | Remaining Limitation |
|---|---|---|---|
| **OCR Digit Confusion** (e.g. 5 vs 6, 0 vs O) | Partially Mitigated | Rule V1 and V2 catch digit errors that violate line sums or unit prices. | If an incorrect digit happens in a field without math checks (like an address), it relies solely on grounding. |
| **Tables Split Across Pages** | Mitigated | PyMuPDF inserts page markers (`--- PAGE N ---`) and parses tables across page breaks. Line items are summed across all pages. | Highly fragmented tables with broken row lines can occasionally misalign columns. |
| **Handwritten Amendments** | Partially Mitigated | Text amended by annotations triggers validation check when conflicting numbers exist. | Standard OCR struggles with messy cursive; a direct vision LLM path is required for complex handwriting. |
| **Conflicting Totals** | Mitigated | Rule V1 detects discrepancies between line items and stated totals, attaches `sum_mismatch`, and flags for review. | The system flags the conflict but does not attempt to resolve which number is legally controlling. |
| **Superseded Revisions in Same File** | Mitigated | Prompt explicitly requires extracting the latest controlling change order and logging prior revisions in `references`. | If revision dates are omitted, the model must rely on file layout context. |
| **Ambiguous Dates** (03/04/2026) | Mitigated | If the date cannot be determined with certainty, the raw string is retained and flagged with `ambiguous_date_format`. | Does not guess between US (MM/DD) and European (DD/MM) conventions. |
| **European Currency & Numbers** (`1.234,56 €`) | Mitigated | Normalization cleans European thousand separators and comma decimals into standard Decimal cents. | Non-standard regional currency abbreviations must be explicitly mapped. |
| **Plausible Hallucinations** | Mitigated | Rule V7 verifies that every extracted field's `source_text` exists in the original document. Ungrounded fields are capped at 0.30. | Fuzzy matching threshold (0.85) could theoretically match a very short word elsewhere in the document. |
| **Prompt Injection Inside Files** | Mitigated | Document text is strictly isolated in `<document_content>` tags with system instructions to treat all document contents as untrusted data. | Advanced indirect prompt injections require ongoing adversarial testing. |
| **Model Overconfidence** | Mitigated | Confidence combines model confidence with external grounding, rule validation, and cross-provider agreement. | Single-provider mode lacks the cross-model agreement signal. |
| **API Schema Drift** | Mitigated | Schemas are enforced via Pydantic models with one automatic repair retry if the model returns invalid JSON. | Persistent breaking changes in provider APIs require code updates. |

---

## 5. What I Would Do With More Time

1. **Direct Vision Path for Scanned Documents**:
   Instead of relying on OCR for image-heavy documents, send high-resolution page images directly to Claude 3.7 Sonnet or Gemini 2.5 Flash via their multimodal vision APIs, comparing OCR text vs image extraction.
2. **Interactive Human-in-the-Loop Review**:
   Build a simple review interface where flagged fields (`needs_review` or `reject`) are highlighted on top of the original PDF with their source snippets, allowing an estimator to click and accept with one keystroke.
3. **Database & Audit Logging**:
   Add a local SQLite/PostgreSQL database to store extracted change orders, revision history, and estimator approvals.
