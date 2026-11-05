"""Run every demo scenario headlessly and assert the expected outcome. Run before every deploy.

Usage:
  python scripts/smoke_test.py                      # offline provider (free, deterministic)
  python scripts/smoke_test.py --provider anthropic # the same scenarios through Claude
  python scripts/smoke_test.py --provider gemini    # the same scenarios through Gemini

Each scenario runs on its own fresh temporary database, so results never depend on order.
Exit code 0 = all green.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, seed  # noqa: E402
from core.llm.base import LLMError, get_provider  # noqa: E402
from core.scenarios import run_scenario  # noqa: E402
from core.submissions import list_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["offline", "anthropic", "gemini"], default="offline")
    parser.add_argument("--with-history", action="store_true", help="also replay the 16 history submissions")
    args = parser.parse_args()
    try:
        provider = get_provider(args.provider)
    except LLMError as exc:
        print(f"Cannot use provider {args.provider}: {exc} (put it in .env)")
        return 2
    print(f"Smoke test with provider={provider.name} model={provider.model}\n")
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        config.UPLOAD_DIR = Path(tmp) / "uploads"
        for scenario in list_scenarios():
            os.environ["VG_DB_PATH"] = str(Path(tmp) / f"{scenario['id']}.db")
            seed.ensure_ready(with_history=False)
            started = time.perf_counter()
            results = run_scenario(scenario["id"], provider=provider)
            for r in results:
                mark = "PASS" if r["ok"] else "FAIL"
                failures += not r["ok"]
                print(f"[{mark}] {scenario['id']:<24} {r['step']:<9} {r.get('status', '?'):<9} "
                      f"{(r.get('sub_status') or ''):<25} risk={r.get('risk', '-')}")
                for p in r["problems"]:
                    print(f"       ! {p}")
            print(f"       ({time.perf_counter() - started:.1f}s)")
        if args.with_history:
            os.environ["VG_DB_PATH"] = str(Path(tmp) / "history.db")
            replayed = seed.ensure_ready(with_history=True)["history_replayed"]
            print(f"[PASS] history backfill replayed {replayed} submissions")
    print("\nALL GREEN" if not failures else f"\n{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
