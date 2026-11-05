"""Generate RULES.md from config/rules.yaml and config/policy.yaml (so the doc never drifts from the code).

Usage:  python scripts/export_rules.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ROOT  # noqa: E402
from core.rules import catalogue, catalogue_version, policy  # noqa: E402

STAGES = {"S2": "S2 Completeness", "S3": "S3 Document understanding", "S4": "S4 Format & checksum",
          "S5": "S5 Consistency & simulated registry", "S6": "S6 Duplicates & fraud patterns", "S7": "S7 Sanctions",
          "any": "System"}


def main() -> None:
    pol = policy()
    t = pol["thresholds"]
    lines = [
        "# Rules and decision policy",
        "",
        f"Generated from `config/rules.yaml` (version {catalogue_version()}) and `config/policy.yaml` "
        f"(version {pol['version']}) by `python scripts/export_rules.py`. The in-app **Rules & policy** page shows the same data.",
        "",
        "## Decision policy (deterministic; an LLM never decides)",
        "",
        f"1. **REJECTED** if any of `{'`, `'.join(pol['reject']['trigger_rules'])}` fires, or there are "
        f"{pol['reject']['min_critical_findings']}+ CRITICAL findings, or more than "
        f"{pol['reject']['max_failed_resubmissions']} failed resubmissions.",
        f"2. **PENDING** if any finding blocks approval (all HIGH/CRITICAL plus the WARNs marked below) or the risk "
        f"score is >= {t['approve_max_risk']}. Sub-status *awaiting vendor* when every blocker has resolver = vendor; "
        "otherwise *awaiting internal review*.",
        f"3. **APPROVED** otherwise (implies every document confidence >= {t['doc_confidence_min']}, no possible "
        f"sanctions match, risk < {t['approve_max_risk']}).",
        "",
        f"Risk score = min({pol['risk_cap']}, sum of weights): "
        + ", ".join(f"{k} = {v}" for k, v in pol["risk_weights"].items()) + ".",
        "",
        "| Threshold | Value |",
        "|---|---|",
        *[f"| `{k}` | {v} |" for k, v in t.items()],
        "",
        "## Rule catalogue",
        "",
        "Resolver: **vendor** = the vendor can fix it; **internal** = a person on our side must judge it.",
        "",
    ]
    by_stage: dict[str, list[dict]] = {}
    for rule in catalogue().values():
        by_stage.setdefault(rule["stage"], []).append(rule)
    for stage, rules in by_stage.items():
        lines += [f"### {STAGES.get(stage, stage)}", "", "| ID | Rule | Severity | Resolver | Blocks approval | Rationale |",
                  "|---|---|---|---|---|---|"]
        for r in rules:
            lines.append(f"| `{r['id']}` | {r['title']} | {r['severity']} | {r['resolver']} | "
                         f"{'yes' if r['blocks_approval'] else 'no'} | {r['rationale']} |")
        lines.append("")
    lines += [
        "## Formats verified (sources checked 2026-11-01)",
        "",
        "| Identifier | Rule implemented | Source |",
        "|---|---|---|",
        "| PAN | `^[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]$`; 4th letter = holder type (C company, F firm/LLP, P individual...) | Income Tax Department PAN FAQ |",
        "| GSTIN | state code + PAN + entity no. + `Z` + Luhn mod-36 check char; state 25/28/96/99 rejected | GSTN state master; checksum verified on 27AAPFU0939F1ZV (the spec's 29AABCT1332L1ZS is invalid: check char should be A) |",
        "| IFSC | `^[A-Z]{4}0[A-Z0-9]{6}$`; bank code vs bank name (20 major banks) | RBI format; Razorpay IFSC dataset |",
        "| Indian account | 9-18 digits, kept as string | RBI guidance |",
        "| EIN | 9 digits, IRS-issued 2-digit prefix (83 valid) | irs.gov valid EIN prefixes |",
        "| ABA routing | 3-7-1 checksum + Federal Reserve prefix ranges | ABA / Federal Reserve |",
        "| UK sort code / account | 6 digits / 8 digits (6-7 left-padded; 9-10 manual review) | Pay.UK |",
        "| UK VAT | GB/XI + 9 or 12 digits, mod-97 remainder 0/42/55 (soft check) | HMRC (algorithm unofficial) |",
        "| UK company number | 8 digits or 2-letter prefix + 6 digits | Companies House |",
        "| Sanctions | OFAC SDN + consolidated, entity + individual names and aliases; composite fuzzy score | US Treasury OFAC SLS |",
    ]
    (ROOT / "RULES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote RULES.md")


if __name__ == "__main__":
    main()
