"""Run a demo scenario end to end and compare with its expected outcome.

Used by tests/test_scenarios.py and scripts/smoke_test.py. A resubmission step behaves
exactly like the vendor: it takes the token from the link in the previous step's email
(S9 output), resolves it, and resubmits through the same pipeline.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import tokens
from core.pipeline.runner import run_pipeline
from core.submissions import draft_from_folder, get_submission, load_scenario


def token_from_link(link: str) -> str:
    return parse_qs(urlparse(link).query).get("token", [""])[0]


def run_scenario(scenario_id: str, provider=None) -> list[dict]:
    meta = load_scenario(scenario_id)
    results, link = [], None
    for step in meta["steps"]:
        parent_id, token = None, None
        if step["kind"] == "resubmit":
            token = token_from_link(link or "")
            parent_id, reason = tokens.resolve(token)
            if not parent_id:
                results.append({"step": step["dir"], "ok": False, "problems": [f"token unusable: {reason}"]})
                break
        draft = draft_from_folder(Path(meta["folder"]) / step["dir"], f"scenario:{scenario_id}",
                                  parent_id=parent_id, token=token)
        submission_id = ""
        for event in run_pipeline(draft, provider=provider):
            if event.phase == "completed":
                submission_id = event.details["submission_id"]
                if event.stage == "S9":
                    link = event.details.get("resubmission_link")
        sub = get_submission(submission_id)
        results.append(check(step, sub))
    return results


def check(step: dict, sub: dict) -> dict:
    expect = step["expect"]
    rules = {f["rule_id"] for f in sub["findings"]}
    problems = []
    if sub["status"] != expect["status"]:
        problems.append(f"status {sub['status']} != expected {expect['status']}")
    if "sub_status" in expect and sub["sub_status"] != expect["sub_status"]:
        problems.append(f"sub_status {sub['sub_status']} != expected {expect['sub_status']}")
    missing = set(expect.get("rules", [])) - rules
    if missing:
        problems.append(f"expected rules not fired: {sorted(missing)}")
    if sub["status"] != "APPROVED" and not any(m["audience"] == "vendor" for m in sub["outbox"]):
        problems.append("no vendor email for a non-approved outcome")
    return {"step": step["dir"], "submission_id": sub["id"], "status": sub["status"], "sub_status": sub["sub_status"],
            "risk": sub["risk_score"], "rules": sorted(rules), "ok": not problems, "problems": problems}
