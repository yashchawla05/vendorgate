"""Decision engine unit tests: the policy, rule by rule."""
from core.decision import AWAITING_REVIEW, AWAITING_VENDOR, decide, risk
from core.rules import catalogue, make_finding, policy


def f(rule_id: str):
    return make_finding(rule_id, "test")


def test_no_findings_is_approved():
    d = decide([], policy())
    assert d.status == "APPROVED" and d.risk_score == 0


def test_non_blocking_warns_still_approve():
    d = decide([f("FRD-005"), f("CON-003")], policy())
    assert d.status == "APPROVED" and d.risk_score == 10


def test_blocking_warn_is_pending():
    assert decide([f("DOC-003")], policy()).status == "PENDING"


def test_vendor_fixable_only_is_awaiting_vendor():
    d = decide([f("COMP-002"), f("FMT-IFSC")], policy())
    assert (d.status, d.sub_status) == ("PENDING", AWAITING_VENDOR)


def test_any_internal_blocker_is_internal_review():
    d = decide([f("COMP-002"), f("CON-004")], policy())
    assert (d.status, d.sub_status) == ("PENDING", AWAITING_REVIEW)


def test_single_critical_without_trigger_is_pending():
    # E1 shape: CON-002 CRITICAL + CON-004 HIGH -> pending, not rejected
    d = decide([f("CON-002"), f("CON-004")], policy())
    assert d.status == "PENDING" and d.risk_score == 60


def test_reject_triggers():
    assert decide([f("FRD-001")], policy()).status == "REJECTED"
    assert decide([f("SAN-001")], policy()).status == "REJECTED"


def test_two_criticals_reject():
    d = decide([f("CON-002"), f("CON-002")], policy())
    assert d.status == "REJECTED" and "CRITICAL" in d.reasons[0]


def test_too_many_failed_resubmissions_reject():
    assert decide([f("COMP-002")], policy(), failed_resubmissions=4).status == "REJECTED"
    assert decide([f("COMP-002")], policy(), failed_resubmissions=3).status == "PENDING"


def test_risk_score_is_capped_and_itemised():
    score, contributions = risk([f("CON-002")] * 3, policy())
    assert score == 100 and len(contributions) == 3 and contributions[0]["points"] == 40


def test_high_risk_from_warns_alone_blocks():
    # six non-blocking WARNs = 30 points = at the approval limit
    d = decide([f("FRD-005")] * 6, policy())
    assert d.status == "PENDING" and d.sub_status == AWAITING_REVIEW


def test_deterministic():
    findings = [f("CON-007"), f("FRD-004"), f("REG-003")]
    assert decide(findings, policy()) == decide(findings, policy())


def test_every_high_or_critical_rule_blocks():
    for rule in catalogue().values():
        if rule["severity"] in ("HIGH", "CRITICAL"):
            assert rule["blocks_approval"], rule["id"]
