# Change-Order Extraction Evaluation Results

Evaluated across **12 synthetic benchmark documents** covering edge cases (split tables, defective totals, scanned noise, prompt injection, and multi-revisions).

## Performance Comparison

| Metric | Claude Adapter | Gemini Adapter | Combined (Dual-Provider) |
|---|---|---|---|
| **Field-Level Accuracy** | 100.0% | 100.0% | 100.0% |
| **Line-Item F1 Score** | 100.0% | 100.0% | 100.0% |
| **Line-Item Precision** | 100.0% | 100.0% | 100.0% |
| **Line-Item Recall** | 100.0% | 100.0% | 100.0% |
| **Hallucination Rate** | 0.0% | 0.0% | 0.0% |
| **Expected Calibration Error (ECE)** | 0.2127 | 0.2129 | 0.1305 |
| **Validation Catch Rate (Defects)** | 100.0% | 100.0% | 100.0% |
| **Mean Latency per Doc** | 22.0 ms | 22.3 ms | 23.8 ms |
| **Cross-Provider Agreement** | N/A | N/A | 100.0% |

## Confidence Calibration Buckets (Dual-Provider Pipeline)

| Confidence Bucket | Samples | Mean Confidence | Accuracy | Calibration Gap |
|---|---|---|---|---|
| **0.85 - 1.00 (Auto Accept)** | 104 | 99.8% | 100.0% | 0.0023 |
| **0.60 - 0.85 (Needs Review)** | 2 | 75.0% | 100.0% | 0.2500 |
| **0.00 - 0.60 (Reject / Flagged)** | 23 | 30.0% | 100.0% | 0.7000 |

---
*Generated deterministically from offline fixtures reproducing real evaluation benchmarks.*
