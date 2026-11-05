"""Download a fresh OFAC sanctions snapshot into data/sanctions/.

Usage:  python scripts/refresh_sanctions.py

What it fetches (US Treasury OFAC Sanctions List Service, public domain):
  SDN.CSV        Specially Designated Nationals - primary names
  ALT.CSV        SDN aliases (a.k.a / f.k.a / n.k.a)
  CONS_PRIM.CSV  Consolidated (non-SDN) lists - primary names
  CONS_ALT.CSV   Consolidated aliases
The CSVs carry no publication date, so we read <Publish_Date> from the first
kilobyte of SDN.XML with an HTTP Range request.

Facts that shaped this script (verified 2026-11-01):
  - Requests without a User-Agent header get HTTP 403.
  - URLs redirect to short-lived S3 links; always follow redirects, never store them.
  - Downloads can take 1-2 minutes each, so this is a manual script, never run at app start.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import SANCTIONS_DIR  # noqa: E402

BASE = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/"
FILES = ["SDN.CSV", "ALT.CSV", "CONS_PRIM.CSV", "CONS_ALT.CSV"]
HEADERS = {"User-Agent": "VendorGate/1.0 (vendor onboarding demo; sanctions snapshot refresh)"}
TIMEOUT = 300


def fetch(name: str) -> bytes:
    response = requests.get(BASE + name, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response.content


def fetch_publish_info() -> dict:
    """Read Publish_Date and Record_Count from the head of SDN.XML."""
    headers = dict(HEADERS, Range="bytes=0-2047")
    response = requests.get(BASE + "SDN.XML", headers=headers, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    head = response.content[:4096].decode("utf-8", "replace")
    date = re.search(r"<Publish_Date>(\d{2})/(\d{2})/(\d{4})</Publish_Date>", head)
    count = re.search(r"<Record_Count>(\d+)</Record_Count>", head)
    return {
        "publish_date": f"{date.group(3)}-{date.group(1)}-{date.group(2)}" if date else None,
        "record_count": int(count.group(1)) if count else None,
    }


def main() -> None:
    SANCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "source": "U.S. Department of the Treasury, OFAC Sanctions List Service",
        "source_url": BASE,
        "license": "U.S. Government work, public domain (17 U.S.C. 105)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coverage": "US lists only (SDN + Consolidated non-SDN). Not UN, EU, UK HMT or Indian lists.",
        "files": {},
    }
    meta.update(fetch_publish_info())
    for name in FILES:
        print(f"downloading {name} ...", flush=True)
        raw = fetch(name)
        target = SANCTIONS_DIR / (name.lower() + ".gz")
        target.write_bytes(gzip.compress(raw, mtime=0))
        meta["files"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        print(f"  {len(raw):,} bytes -> {target.name}")
    (SANCTIONS_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print("publish date:", meta["publish_date"], "records:", meta["record_count"])


if __name__ == "__main__":
    main()
