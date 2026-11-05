"""One test per demo scenario: the real pipeline, real files, expected outcome from scenario.json.

These run with the offline provider so they are free and deterministic. The same
scenarios run against Claude with: python scripts/smoke_test.py --provider anthropic
"""
import json

from core import db
from core.llm.base import LLMError
from core.llm.offline_provider import OfflineProvider
from core.pipeline.runner import run_to_completion
from core.scenarios import run_scenario
from core.config import SCENARIO_DIR
from core.submissions import draft_from_folder, get_submission


def assert_scenario(scenario_id):
    results = run_scenario(scenario_id)
    for r in results:
        assert r["ok"], f"{scenario_id}/{r['step']}: {r['problems']}"
    return results


def test_happy_path(fresh_db):
    [r] = assert_scenario("happy")
    sub = get_submission(r["submission_id"])
    assert sub["risk_score"] < 30
    assert db.query_one("SELECT * FROM vendors WHERE source_submission_id = ?", (r["submission_id"],))


def test_e1_looks_fine_isnt(fresh_db):
    [r] = assert_scenario("e1_looks_fine")
    sub = get_submission(r["submission_id"])
    s5 = next(s for s in sub["stages"] if s["stage"] == "S5")
    rows = {row["field"]: row for row in s5["details"]["comparison"]}
    assert rows["tax.pan"]["status"] == "mismatch"  # field x source: GSTIN chars 3-12 disagree with the PAN
    assert "GSTIN (chars 3-12)" in rows["tax.pan"]["sources"]
    email = next(m for m in sub["outbox"] if m["audience"] == "vendor")
    assert "GST registration certificate" in email["body"] and "PAN" in email["body"]


def test_e2_wrong_documents(fresh_db):
    [r] = assert_scenario("e2_wrong_docs")
    sub = get_submission(r["submission_id"])
    email = next(m for m in sub["outbox"] if m["audience"] == "vendor")
    for item in ("Form W-9", "EIN", "Bank account confirmation letter"):
        assert item in email["body"], item  # itemised request


def test_e3_ghost_vendor(fresh_db):
    [r] = assert_scenario("e3_ghost_vendor")
    sub = get_submission(r["submission_id"])
    vendor_mail = next(m for m in sub["outbox"] if m["audience"] == "vendor")
    internal = next(m for m in sub["outbox"] if m["audience"] == "internal")
    body = vendor_mail["body"].lower()
    for phrase in ("bank account", "account holder", "fraud", "sanction", "duplicate", "frd-", "risk", "existing vendor"):
        assert phrase not in body, phrase  # the neutral notice reveals nothing about detection
    assert "FRD-001" in internal["body"]


def test_e4_pending_fixed_approved(fresh_db):
    first, second = assert_scenario("e4_fix_approved")
    sub = get_submission(second["submission_id"])
    assert sub["version"] == 2 and len(sub["chain"]) == 2  # audit trail shows both submissions
    s6 = next(s for s in sub["stages"] if s["stage"] == "S6")
    changed = {d["field"]: d for d in s6["details"]["diff"]}
    assert changed["bank.ifsc"]["requested"] is True  # the fix was asked for, so no fraud flag
    assert any(d["carried_from"] for d in sub["documents"])  # unchanged documents carried over


def test_e4b_silent_bank_change(fresh_db):
    first, second = assert_scenario("e4b_bank_change")
    sub = get_submission(second["submission_id"])
    frd = next(f for f in sub["findings"] if f["rule_id"] == "FRD-003")
    assert frd["evidence"]["before"] != frd["evidence"]["after"]


def test_e5_sanctions_near_miss(fresh_db):
    [r] = assert_scenario("e5_sanctions_near_miss")
    sub = get_submission(r["submission_id"])
    hit = next(f for f in sub["findings"] if f["rule_id"] == "SAN-002")
    assert 85 <= hit["evidence"]["score"] < 92 and hit["evidence"]["list_date"]


# ---------------------------------------------------------------- reliability
class BrokenProvider(OfflineProvider):
    """Simulates the LLM service failing (timeout, invalid JSON...)."""

    name = "broken"

    def understand_document(self, content, expected_types):
        raise LLMError("simulated timeout")


def test_llm_failure_degrades_to_pending_never_approves(fresh_db):
    draft = draft_from_folder(SCENARIO_DIR / "happy" / "initial", "test")
    sid, events = run_to_completion(draft, provider=BrokenProvider())
    s3 = next(e for e in events if e.stage == "S3")
    sub = get_submission(sid)
    assert s3.status == "degraded" and "did not answer for 4 document(s)" in s3.summary
    assert sub["status"] == "PENDING" and sub["sub_status"] == "awaiting_internal_review"
    assert "DOC-004" in {f["rule_id"] for f in sub["findings"]}
    # The banner names each problem once, with a count, instead of repeating it per document.
    explanation = sub["decision"]["explanation"]
    assert explanation.count("DOC-004") == 1 and "(DOC-004 ×4)" in explanation


def test_stage_crash_is_surfaced_not_swallowed(fresh_db, monkeypatch):
    from core.pipeline import runner

    def boom(ctx):
        raise RuntimeError("bug")

    stages = [(c, n, boom if c == "S6" else fn) for c, n, fn in runner.STAGES]
    monkeypatch.setattr(runner, "STAGES", stages)
    sid, events = run_to_completion(draft_from_folder(SCENARIO_DIR / "happy" / "initial", "test"))
    sub = get_submission(sid)
    assert sub["status"] == "PENDING" and "SYS-001" in {f["rule_id"] for f in sub["findings"]}


def test_prompt_injection_does_not_change_outcome(fresh_db):
    from core.config import HISTORY_DIR

    sid, _ = run_to_completion(draft_from_folder(HISTORY_DIR / "H16", "test"))
    sub = get_submission(sid)
    rules = {f["rule_id"] for f in sub["findings"]}
    assert rules == {"DOC-005"}  # flagged for a human, every other check unaffected
    assert sub["status"] == "PENDING"


def test_corrupt_upload_becomes_a_finding_not_a_crash(fresh_db):
    draft = draft_from_folder(SCENARIO_DIR / "happy" / "initial", "test")
    draft.files["pan_card"] = ("pan_card.pdf", b"%PDF-1.4 this is not really a pdf")
    sid, _ = run_to_completion(draft)
    sub = get_submission(sid)
    assert sub["status"] == "PENDING" and "DOC-002" in {f["rule_id"] for f in sub["findings"]}


def test_same_input_same_decision(fresh_db):
    a, _ = run_to_completion(draft_from_folder(SCENARIO_DIR / "e1_looks_fine" / "initial", "test"))
    b, _ = run_to_completion(draft_from_folder(SCENARIO_DIR / "e1_looks_fine" / "initial", "test"))
    da, dbb = get_submission(a)["decision"], get_submission(b)["decision"]
    assert (da["status"], da["sub_status"], da["risk_score"], json.loads(da["breakdown_json"])) == \
           (dbb["status"], dbb["sub_status"], dbb["risk_score"], json.loads(dbb["breakdown_json"]))


def test_resubmission_token_is_single_use(fresh_db):
    from core import tokens

    results = run_scenario("e4_fix_approved")
    first = get_submission(results[0]["submission_id"])
    assert db.query_one("SELECT used_at FROM tokens WHERE submission_id = ?", (first["id"],))["used_at"]
    assert tokens.resolve("not-a-real-token")[0] is None
