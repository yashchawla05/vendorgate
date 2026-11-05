"""Measure document understanding against ground truth and write EVAL.md.

Usage:
  python scripts/run_eval.py                      # offline provider (free, deterministic)
  python scripts/run_eval.py --provider anthropic # Claude (needs ANTHROPIC_API_KEY; costs tokens)
  python scripts/run_eval.py --provider gemini    # Gemini (needs GEMINI_API_KEY; free tier is rate limited)
  python scripts/run_eval.py --provider anthropic --limit 20

Scoring:
  * classification accuracy: predicted document type == true type
  * field accuracy: only fields that are printed on the document (non-empty truth) are scored;
    values are compared after normalisation (case/punctuation for names, ISO for dates,
    separators for IDs; addresses use fuzzy >= 90 because line breaks vary)
Results for each provider are kept in data/eval/results_<provider>.json and all are summarised in EVAL.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rapidfuzz import fuzz  # noqa: E402

from core import config  # noqa: E402
from core.config import DATA_DIR, EVAL_DIR, ROOT  # noqa: E402
from core.documents.reader import read_document  # noqa: E402
from core.llm.base import LLMError, get_provider  # noqa: E402
from core.documents.dates import DATE_FIELDS, month_first, to_iso_date  # noqa: E402
from core.names import normalise  # noqa: E402
from core.validators.common import compact  # noqa: E402

ID_FIELDS = {"pan", "gstin", "ifsc", "cin", "ein", "account_number", "routing_number", "sort_code", "company_number"}


def values_match(field: str, truth: str, got: str, us_format: bool = False) -> bool:
    if field in DATE_FIELDS:  # scored after the same conversion S3 applies
        return truth == to_iso_date(got, us_format)
    if field in ID_FIELDS:
        return compact(truth) == compact(got)
    if field == "address":
        return fuzz.token_set_ratio(normalise(truth), normalise(got)) >= 90
    return normalise(truth) == normalise(got)


def evaluate(provider_name: str, limit: int | None) -> dict:
    provider = get_provider(provider_name)
    truth_map = json.loads((EVAL_DIR / "ground_truth.json").read_text())
    items = sorted(truth_map.items())
    if limit:
        # Keep scans in a limited run: they are the interesting cases for an LLM.
        scans = [i for i in items if "scan" in i[1]["layout"]]
        items = scans + [i for i in items if i not in scans][: max(0, limit - len(scans))]
    per_doc, tokens_in, tokens_out = [], 0, 0
    for rel, truth in items:
        content = read_document(DATA_DIR / rel, max_pages=config.max_pages_per_doc())
        started = time.perf_counter()
        try:
            result, usage = provider.understand_document(content, [truth["doc_type"]])
            tokens_in += usage.input_tokens
            tokens_out += usage.output_tokens
            error = ""
        except Exception as exc:  # an eval must report failures, not crash
            result, error = None, f"{type(exc).__name__}: {exc}"
        got = {f.name: f for f in result.fields} if result else {}
        us = month_first(result.document_type if result else "", {k: f.value for k, f in got.items()})
        fields = []
        for name, true_value in truth["fields"].items():
            if not true_value:
                continue
            g = got.get(name)
            fields.append({"field": name, "truth": true_value, "got": g.value if g else "",
                           "confidence": g.confidence if g else 0.0,
                           "correct": bool(g) and values_match(name, true_value, g.value, us)})
        per_doc.append({
            "path": rel, "true_type": truth["doc_type"], "layout": truth["layout"],
            "pred_type": result.document_type if result else "error",
            "readable": result.readable if result else False,
            "type_correct": bool(result) and result.document_type == truth["doc_type"],
            "fields": fields, "error": error, "ms": int((time.perf_counter() - started) * 1000),
        })
    return {"provider": provider.name, "model": provider.model, "run_at": datetime.now().isoformat(timespec="seconds"),
            "documents": per_doc, "tokens_in": tokens_in, "tokens_out": tokens_out}


def summarise(res: dict) -> str:
    docs = res["documents"]
    n = len(docs)
    type_ok = sum(d["type_correct"] for d in docs)
    field_stats = defaultdict(lambda: [0, 0])
    layout_stats = defaultdict(lambda: [0, 0])
    conf_ok, conf_bad = [], []
    for d in docs:
        for f in d["fields"]:
            field_stats[f["field"]][0] += f["correct"]
            field_stats[f["field"]][1] += 1
            layout_stats[d["layout"]][0] += f["correct"]
            layout_stats[d["layout"]][1] += 1
            (conf_ok if f["correct"] else conf_bad).append(f["confidence"])
    total_ok = sum(v[0] for v in field_stats.values())
    total = sum(v[1] for v in field_stats.values())
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "-"  # noqa: E731
    mean = lambda xs: f"{sum(xs) / len(xs):.2f}" if xs else "-"  # noqa: E731
    lines = [
        f"### Provider: `{res['provider']}` (model `{res['model']}`), run {res['run_at']}",
        "",
        f"- Documents: **{n}** · classification accuracy **{pct(type_ok, n)}** ({type_ok}/{n})",
        f"- Field accuracy (printed fields only): **{pct(total_ok, total)}** ({total_ok}/{total})",
        f"- Mean reported confidence: correct fields {mean(conf_ok)}, wrong/missed fields {mean(conf_bad)}",
        f"- Tokens: {res['tokens_in']:,} in / {res['tokens_out']:,} out",
        "",
        "| Field | Accuracy | n |", "|---|---|---|",
    ]
    for name, (ok, tot) in sorted(field_stats.items()):
        lines.append(f"| {name} | {pct(ok, tot)} | {tot} |")
    lines += ["", "| Layout | Field accuracy | n fields |", "|---|---|---|"]
    for name, (ok, tot) in sorted(layout_stats.items()):
        lines.append(f"| {name} | {pct(ok, tot)} | {tot} |")
    misses = [(d["path"], f) for d in docs for f in d["fields"] if not f["correct"]]
    wrong_types = [d for d in docs if not d["type_correct"]]
    if wrong_types:
        lines += ["", "Misclassified / unreadable documents:", ""]
        lines += [f"- `{d['path']}`: true `{d['true_type']}`, predicted `{d['pred_type']}`"
                  f"{' (unreadable)' if not d['readable'] else ''}{' ' + d['error'] if d['error'] else ''}"
                  for d in wrong_types]
    if misses:
        lines += ["", f"Field misses (first 15 of {len(misses)}):", ""]
        lines += [f"- `{p}` **{f['field']}**: expected `{f['truth']}`, got `{f['got'] or '(none)'}`" for p, f in misses[:15]]
    return "\n".join(lines)


HEADER = """# Extraction evaluation

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
"""


def write_markdown() -> None:
    sections = []
    keys = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
    for provider in ("anthropic", "gemini", "offline"):
        path = EVAL_DIR / f"results_{provider}.json"
        if path.exists():
            sections.append(summarise(json.loads(path.read_text())))
        else:
            sections.append(f"### Provider: `{provider}`\n\nNot run yet. "
                            f"Run `python scripts/run_eval.py --provider {provider}` (needs {keys.get(provider, 'no key')}).")
    (ROOT / "EVAL.md").write_text(HEADER + "\n" + "\n\n".join(sections) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="offline", choices=["offline", "anthropic", "gemini"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    try:
        res = evaluate(args.provider, args.limit)
    except LLMError as exc:
        sys.exit(f"Cannot use provider {args.provider}: {exc} (put it in .env)")
    (EVAL_DIR / f"results_{args.provider}.json").write_text(json.dumps(res, indent=2))
    write_markdown()
    print(summarise(res))


if __name__ == "__main__":
    main()
