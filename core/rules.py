"""Load the rule catalogue and decision policy, and build findings from rule IDs.

Stages call make_finding("CON-002", message, ...). Severity, category, resolver and
whether it blocks approval are looked up in config/rules.yaml, never hard-coded in a stage.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from core.config import CONFIG_DIR
from core.models import Finding


@lru_cache(maxsize=1)
def catalogue() -> dict[str, dict]:
    data = yaml.safe_load((CONFIG_DIR / "rules.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["rules"]}


@lru_cache(maxsize=1)
def catalogue_version() -> str:
    return yaml.safe_load((CONFIG_DIR / "rules.yaml").read_text(encoding="utf-8"))["version"]


@lru_cache(maxsize=1)
def policy() -> dict:
    return yaml.safe_load((CONFIG_DIR / "policy.yaml").read_text(encoding="utf-8"))


def threshold(name: str) -> float:
    return policy()["thresholds"][name]


def make_finding(rule_id: str, message: str, *, field: str = "", evidence: dict | None = None,
                 vendor_request: str = "") -> Finding:
    """Create a finding; unknown rule IDs fail loudly so the catalogue stays the source of truth."""
    rule = catalogue()[rule_id]
    return Finding(
        rule_id=rule_id,
        severity=rule["severity"],
        category=rule["category"],
        title=rule["title"],
        message=message,
        resolver=rule["resolver"],
        blocks_approval=bool(rule["blocks_approval"]),
        field=field,
        evidence=evidence or {},
        vendor_request=vendor_request,
    )
