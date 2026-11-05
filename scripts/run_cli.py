"""Run one scenario (or a submission folder) through the pipeline from the command line.

Usage:
  python scripts/run_cli.py happy                 # scenario id (see data/scenarios/)
  python scripts/run_cli.py e4_fix_approved       # multi-step scenarios run every step in order
  python scripts/run_cli.py --folder path/to/dir  # any folder with submission.json + files
  python scripts/run_cli.py happy --provider anthropic   # or --provider gemini
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm.base import LLMError, get_provider  # noqa: E402
from core.pipeline.runner import run_pipeline  # noqa: E402
from core.seed import ensure_ready  # noqa: E402
from core.submissions import draft_from_folder, get_submission, load_scenario  # noqa: E402


def run_draft(draft, provider) -> str:
    submission_id = ""
    for e in run_pipeline(draft, provider=provider):
        if e.phase == "completed":
            submission_id = e.details["submission_id"]
            print(f"  {e.stage:<4} {e.name:<42} {e.status:<9} {e.duration_ms:>6} ms  {e.summary}")
            for f in e.findings:
                print(f"         - [{f.severity}] {f.rule_id} {f.message}")
    return submission_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("--folder")
    parser.add_argument("--provider", choices=["offline", "anthropic", "gemini"])
    args = parser.parse_args()
    ensure_ready(with_history=False)
    try:
        provider = get_provider(args.provider)
    except LLMError as exc:
        sys.exit(f"Cannot use provider {args.provider}: {exc} (put it in .env)")
    print(f"provider: {provider.name} ({provider.model})")
    if args.folder:
        steps = [{"dir": "", "kind": "submit"}]
        base = Path(args.folder)
    else:
        meta = load_scenario(args.scenario)
        steps, base = meta["steps"], Path(meta["folder"])
        print(f"scenario: {meta['title']}")
    previous = None
    for step in steps:
        # A resubmission step continues the chain of the previous step (the UI does this via the emailed link).
        parent = previous if step["kind"] == "resubmit" else None
        draft = draft_from_folder(base / step["dir"], f"scenario:{args.scenario or 'folder'}", parent_id=parent)
        print(f"\n== step: {step['kind']} ({step['dir'] or base.name})")
        previous = run_draft(draft, provider)
        sub = get_submission(previous)
        print(f"  => {sub['status']} {sub['sub_status'] or ''} risk={sub['risk_score']}  expected: {step.get('expect')}")


if __name__ == "__main__":
    main()
