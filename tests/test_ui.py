"""UI tests with Streamlit's AppTest: every page renders, and the key journeys work end to end
through the real pages (scenario -> live run -> detail -> vendor link -> resubmit -> approved;
review queue decision)."""
import pytest
from streamlit.testing.v1 import AppTest

from core import db
from core.config import ROOT

APP = str(ROOT / "app.py")

PAGES = ["views/overview.py", "views/new_submission.py", "views/live_run.py", "views/submission_detail.py",
         "views/review_queue.py", "views/vendors.py", "views/outbox.py", "views/rules.py", "views/audit_log.py",
         "views/assumptions.py", "views/health.py", "views/about.py"]


def app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def no_errors(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(fresh_db, page):
    at = app()
    at.switch_page(page).run()
    no_errors(at)
    # every page has the top bar: Light / Dark switch (with its script) and the About me link
    switch = [h.value for h in at.html if 'data-vg-theme="Dark"' in h.value]
    assert switch and "<script>" in switch[0] and 'data-vg-theme="Light"' in switch[0]
    assert any(link.proto.label == "About me" for link in at.get("page_link"))


def run_scenario_via_ui(at: AppTest, scenario_id: str) -> str:
    at.switch_page("views/new_submission.py").run()
    at.button(key=f"run_{scenario_id}").click().run()
    no_errors(at)
    return at.session_state["last_run_id"]


def test_e4_journey_through_the_ui(fresh_db):
    at = app()
    first = run_scenario_via_ui(at, "e4_fix_approved")
    assert db.query_one("SELECT status FROM submissions WHERE id = ?", (first,))["status"] == "PENDING"
    # Reviewer opens detail and follows the vendor link from the (simulated) email.
    at.switch_page("views/submission_detail.py").run()
    link_button = next(b for b in at.button if "resubmission link" in b.label)
    link_button.click().run()
    no_errors(at)
    assert [t.value for t in at.title] == ["Update your submission"]
    # AppTest does not keep a script-initiated page switch for the next rerun (a browser does,
    # via the URL), so select the page explicitly; the token is remembered in the session.
    at.switch_page("views/resubmit.py").run()
    helper = next(b for b in at.button if "corrected files" in b.label)
    helper.click().run()
    no_errors(at)
    second = at.session_state["last_run_id"]
    row = db.query_one("SELECT status, parent_id FROM submissions WHERE id = ?", (second,))
    assert row["status"] == "APPROVED" and row["parent_id"] == first


def test_review_queue_requires_reason_and_records_decision(fresh_db):
    at = app()
    sid = run_scenario_via_ui(at, "e5_sanctions_near_miss")
    at.switch_page("views/review_queue.py").run()
    no_errors(at)
    at.radio[0].set_value("approve")
    at.text_input[0].set_value("Asha (compliance)")
    at.text_area[0].set_value("short")
    at.button[-1].click().run()
    assert any("reason" in e.value for e in at.error)  # mandatory reason enforced
    assert db.query_one("SELECT status FROM submissions WHERE id = ?", (sid,))["status"] == "PENDING"
    at.radio[0].set_value("approve")
    at.text_area[0].set_value("False positive: listed entity is an Iranian shipping firm; vendor is an Indian company "
                              "incorporated in 2016 with different directors.")
    at.button[-1].click().run()
    no_errors(at)
    row = db.query_one("SELECT status, system_status FROM submissions WHERE id = ?", (sid,))
    assert (row["status"], row["system_status"]) == ("APPROVED", "PENDING")
    assert db.query_one("SELECT * FROM audit_events WHERE event = 'review_approve' AND submission_id = ?", (sid,))


def submit(at: AppTest) -> None:
    next(b for b in at.button if b.label == "Submit for verification").click().run()


@pytest.mark.parametrize("sample_id, status", [("us1_clean_llc", "APPROVED"), ("in3_gstin_typo", "PENDING")])
def test_form_sample_fills_the_form_and_submits(fresh_db, sample_id, status):
    at = app()
    at.switch_page("views/new_submission.py").run()
    at.selectbox(key="f_sample").set_value(sample_id).run()
    no_errors(at)
    assert at.text_input(key="f_legal_name").value  # fields are filled in, not just stored
    assert at.selectbox(key="f_country").value == sample_id[:2].upper()
    submit(at)
    no_errors(at)
    from core.submissions import get_submission

    sub = get_submission(at.session_state["last_run_id"])
    assert sub["status"] == status and sub["source"] == "portal"
    assert len(sub["documents"]) >= 2  # the sample's files were attached


def test_unticking_a_sample_document_leaves_it_out(fresh_db):
    at = app()
    at.switch_page("views/new_submission.py").run()
    at.selectbox(key="f_sample").set_value("us1_clean_llc").run()
    at.checkbox(key="f_use_bank_letter").uncheck()
    submit(at)
    no_errors(at)
    from core.submissions import get_submission

    sub = get_submission(at.session_state["last_run_id"])
    assert sub["status"] == "PENDING" and "COMP-002" in {f["rule_id"] for f in sub["findings"]}


def test_about_page_shows_the_cv_and_live_project_figures(fresh_db):
    from core.rules import catalogue

    at = app()
    at.switch_page("views/about.py").run()
    no_errors(at)
    page = " ".join(m.value for m in at.markdown)
    assert "Licious" in page and "Business Analyst Intern" in page
    assert f"{len(catalogue())} explicit rules" in page  # computed, not typed in
    assert at.get("image"), "the CV is shown as an image"
    [download] = at.get("download_button")
    assert download.proto.label == "Download CV"


def test_resubmit_page_rejects_bad_token(fresh_db):
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["token"] = "nope"
    at.run()
    at.switch_page("views/resubmit.py").run()
    assert any("not valid" in e.value for e in at.error)


def test_health_page_shows_gemini_when_only_a_gemini_key_is_set(fresh_db, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")  # nothing is called: the check button is not clicked
    at = app()
    at.switch_page("views/health.py").run()
    no_errors(at)
    page = " ".join(m.value for m in at.markdown)
    assert "gemini" in page and "gemini-3.5-flash-lite" in page
    assert any("per minute" in c.value for c in at.caption)
