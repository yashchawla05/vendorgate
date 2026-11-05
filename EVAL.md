# Extraction evaluation

How well does S3 (document understanding) read the documents? Ground truth comes from
`scripts/generate_data.py`, which records the exact values printed on every synthetic
document (`data/eval/ground_truth.json`): scenario files, history files, two layout
variants per document type, and scanned images (rotated, noisy JPEG / image-only PDF).

Re-run: `python scripts/run_eval.py` (offline), or with `--provider anthropic` / `--provider gemini`.

How to read this:
* The **offline** provider only reads PDF text layers, so scans count as misses by design.
  That is the reason the LLM exists in this pipeline: scans, unseen layouts, and judging what a document *is*.
* Low confidence and unreadable documents never pass silently: S3 turns them into findings (DOC-002/003)
  and the decision becomes PENDING.

### Provider: `anthropic`

Not run yet. Run `python scripts/run_eval.py --provider anthropic` (needs ANTHROPIC_API_KEY).

### Provider: `gemini` (model `gemini-3.5-flash-lite`), run 2026-11-03T11:42:10

- Documents: **110** · classification accuracy **100%** (110/110)
- Field accuracy (printed fields only): **100%** (445/445)
- Mean reported confidence: correct fields 0.99, wrong/missed fields -
- Tokens: 82,550 in / 34,479 out

| Field | Accuracy | n |
|---|---|---|
| account_holder | 100% | 35 |
| account_number | 100% | 35 |
| address | 100% | 26 |
| bank_name | 100% | 35 |
| cin | 100% | 20 |
| company_name | 100% | 24 |
| company_number | 100% | 4 |
| constitution | 100% | 22 |
| date | 100% | 24 |
| declaration_date | 100% | 1 |
| ein | 100% | 4 |
| gstin | 100% | 22 |
| ifsc | 100% | 27 |
| incorporation_date | 100% | 24 |
| legal_name | 100% | 23 |
| letter_date | 100% | 27 |
| name | 100% | 28 |
| pan | 100% | 25 |
| registration_date | 100% | 22 |
| routing_number | 100% | 4 |
| signature_date | 100% | 4 |
| sort_code | 100% | 4 |
| tax_classification | 100% | 4 |
| trade_name | 100% | 1 |

| Layout | Field accuracy | n fields |
|---|---|---|
| A | 100% | 240 |
| A-scan | 100% | 7 |
| B | 100% | 193 |
| B-scan | 100% | 5 |

### Provider: `offline` (model `rules-v1`), run 2026-11-03T11:28:37

- Documents: **110** · classification accuracy **97%** (107/110)
- Field accuracy (printed fields only): **97%** (433/445)
- Mean reported confidence: correct fields 0.90, wrong/missed fields 0.00
- Tokens: 0 in / 0 out

| Field | Accuracy | n |
|---|---|---|
| account_holder | 97% | 35 |
| account_number | 97% | 35 |
| address | 96% | 26 |
| bank_name | 97% | 35 |
| cin | 100% | 20 |
| company_name | 100% | 24 |
| company_number | 100% | 4 |
| constitution | 95% | 22 |
| date | 96% | 24 |
| declaration_date | 100% | 1 |
| ein | 100% | 4 |
| gstin | 95% | 22 |
| ifsc | 96% | 27 |
| incorporation_date | 100% | 24 |
| legal_name | 96% | 23 |
| letter_date | 100% | 27 |
| name | 96% | 28 |
| pan | 96% | 25 |
| registration_date | 95% | 22 |
| routing_number | 100% | 4 |
| signature_date | 100% | 4 |
| sort_code | 100% | 4 |
| tax_classification | 100% | 4 |
| trade_name | 100% | 1 |

| Layout | Field accuracy | n fields |
|---|---|---|
| A | 100% | 240 |
| A-scan | 0% | 7 |
| B | 100% | 193 |
| B-scan | 0% | 5 |

Misclassified / unreadable documents:

- `eval/docs/in_co_cancelled_cheque_A_scan.jpg`: true `cancelled_cheque`, predicted `other` (unreadable)
- `eval/docs/in_co_gst_certificate_B_scan.pdf`: true `gst_certificate`, predicted `other` (unreadable)
- `eval/docs/in_co_pan_card_A_scan.jpg`: true `pan_card`, predicted `other` (unreadable)

Field misses (first 15 of 12):

- `eval/docs/in_co_cancelled_cheque_A_scan.jpg` **account_holder**: expected `Orchid Bay Ceramics Private Limited`, got `(none)`
- `eval/docs/in_co_cancelled_cheque_A_scan.jpg` **account_number**: expected `137189246387`, got `(none)`
- `eval/docs/in_co_cancelled_cheque_A_scan.jpg` **ifsc**: expected `CNRB0SYN201`, got `(none)`
- `eval/docs/in_co_cancelled_cheque_A_scan.jpg` **bank_name**: expected `Canara Bank`, got `(none)`
- `eval/docs/in_co_gst_certificate_B_scan.pdf` **gstin**: expected `29ZZACO7703M1ZZ`, got `(none)`
- `eval/docs/in_co_gst_certificate_B_scan.pdf` **legal_name**: expected `Orchid Bay Ceramics Private Limited`, got `(none)`
- `eval/docs/in_co_gst_certificate_B_scan.pdf` **address**: expected `48, Park Street, Mangaluru, Karnataka 163910`, got `(none)`
- `eval/docs/in_co_gst_certificate_B_scan.pdf` **registration_date**: expected `2018-06-02`, got `(none)`
- `eval/docs/in_co_gst_certificate_B_scan.pdf` **constitution**: expected `Private Limited Company`, got `(none)`
- `eval/docs/in_co_pan_card_A_scan.jpg` **pan**: expected `ZZACO7703M`, got `(none)`
- `eval/docs/in_co_pan_card_A_scan.jpg` **name**: expected `Orchid Bay Ceramics Private Limited`, got `(none)`
- `eval/docs/in_co_pan_card_A_scan.jpg` **date**: expected `2009-08-11`, got `(none)`
