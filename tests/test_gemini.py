"""Gemini provider against a mock HTTP server, plus provider selection.

Like the Anthropic tests, these never touch the network: the google-genai SDK is given an httpx
MockTransport, so request shape, schema validation, rate-limit handling and failures are tested for free.
The last test runs every demo scenario through the Gemini code path, with a fake "model" that answers
like the offline rules would, to prove the wiring end to end (live accuracy is measured by run_eval.py).
"""
import datetime
import json
import re

import httpx
import pytest
from google import genai
from google.genai import types

from core import comms, config, db
from core.config import DATA_DIR, SCENARIO_DIR
from core.documents.dates import DATE_FIELDS, month_first, to_iso_date
from core.documents.reader import DocumentContent, read_document
from core.llm.base import LLMError, get_provider
from core.llm.gemini_provider import GeminiProvider, RateLimiter, quota_details
from core.llm.offline_provider import OfflineProvider
from core.llm.schemas import EmailDraft, ExtractedField, NameVerdict
from core.pipeline.context import DocResult
from core.pipeline.stages_intake import _normalise_dates
from core.scenarios import run_scenario
from core.submissions import get_submission, list_scenarios

MODEL = "gemini-3.5-flash-lite"
GOOD = {
    "document_type": "gst_certificate", "type_confidence": 0.97, "readable": True,
    "fields": [{"name": "gstin", "value": "29ZZSCK1133Y1Z9", "confidence": 0.98, "evidence": "Registration Number 29ZZSCK1133Y1Z9"}],
    "suspicious_instructions": False, "notes": "",
}


def _reply(obj, finish="STOP", **extra) -> httpx.Response:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    body = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 1300, "candidatesTokenCount": 140, "thoughtsTokenCount": 60},
            "modelVersion": MODEL, **extra}
    return httpx.Response(200, json=body)


def _error(code: int, status: str, message: str, details=None) -> httpx.Response:
    return httpx.Response(code, json={"error": {"code": code, "status": status, "message": message,
                                                "details": details or []}})


def _rate_limited(quota_id: str, delay: str = "7s") -> httpx.Response:
    return _error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                         "quotaId": quota_id}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
    ])


def _provider(handler, sleeps=None, fallbacks=()) -> GeminiProvider:
    client = genai.Client(api_key="test-key", http_options=types.HttpOptions(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    provider = GeminiProvider(model=MODEL, client=client, limiter=RateLimiter(),
                              sleep=(sleeps.append if sleeps is not None else lambda s: None), fallbacks=list(fallbacks))
    provider.per_minute = 0  # pacing has its own test
    return provider


def _content():
    return read_document(SCENARIO_DIR / "happy" / "initial" / "gst_certificate.pdf")


# ---------------------------------------------------------------- request and response
def test_gemini_parses_structured_output_and_counts_tokens():
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        seen["key"] = request.headers.get("x-goog-api-key")
        return _reply(GOOD)

    result, usage = _provider(handler).understand_document(_content(), ["gst_certificate"])
    assert result.document_type == "gst_certificate" and result.fields[0].value == "29ZZSCK1133Y1Z9"
    assert usage.provider == "gemini" and usage.model == MODEL
    assert usage.input_tokens == 1300 and usage.output_tokens == 200  # thinking tokens are billed as output
    assert seen["url"].endswith(f"/models/{MODEL}:generateContent") and seen["key"] == "test-key"
    body = seen["body"]
    assert "untrusted" in body["systemInstruction"]["parts"][0]["text"]  # injection stance in the system prompt
    user_text = body["contents"][0]["parts"][0]["text"]
    assert user_text.startswith("<document") and "Kestrel Analytics" in user_text
    assert "gst_certificate" not in user_text.split("</document>")[0]  # no slot hint leaks into the data
    config_ = body["generationConfig"]
    assert config_["responseMimeType"] == "application/json"
    assert "gst_certificate" in json.dumps(config_["responseSchema"])  # the document-type enum is enforced
    assert "thinkingConfig" in config_


def test_gemini_sends_images_for_scans():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _reply(dict(GOOD, document_type="pan_card", fields=[]))

    _provider(handler).understand_document(read_document(DATA_DIR / "samples" / "scanned_pan_card.jpg"), [])
    image = seen["body"]["contents"][0]["parts"][0]["inlineData"]
    # The SDK writes proto field names (mime_type); the API accepts them as well as camelCase.
    assert (image.get("mimeType") or image.get("mime_type")) == "image/jpeg" and image["data"]


def test_gemini_names_and_email_tasks():
    verdict = {"same_entity": "yes", "reason": "Pvt Ltd is an abbreviation of Private Limited"}
    result, _ = _provider(lambda r: _reply(verdict)).adjudicate_names("Kestrel Pvt Ltd", "Kestrel Private Limited", "")
    assert isinstance(result, NameVerdict) and result.same_entity == "yes"
    draft, _ = _provider(lambda r: _reply({"subject": "Documents needed", "body": "Dear vendor"})).draft_email({"status": "PENDING"})
    assert isinstance(draft, EmailDraft) and draft.subject == "Documents needed"


# ---------------------------------------------------------------- failures become LLMError (stage degraded)
def test_gemini_schema_violation_raises():
    bad = dict(GOOD, document_type="passport")  # not an allowed enum value
    with pytest.raises(LLMError, match="schema"):
        _provider(lambda r: _reply(bad)).understand_document(_content(), [])
    with pytest.raises(LLMError, match="schema"):
        _provider(lambda r: _reply("not json at all")).understand_document(_content(), [])


def test_gemini_server_error_raises():
    provider = _provider(lambda r: _error(500, "INTERNAL", "boom"))
    with pytest.raises(LLMError, match="500"):
        provider.understand_document(_content(), [])


def test_gemini_safety_stop_and_blocked_prompt_raise():
    with pytest.raises(LLMError, match="declined"):
        _provider(lambda r: _reply(GOOD, finish="SAFETY")).understand_document(_content(), [])
    blocked = httpx.Response(200, json={"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"},
                                        "usageMetadata": {"promptTokenCount": 10}})
    with pytest.raises(LLMError, match="declined"):
        _provider(lambda r: blocked).understand_document(_content(), [])


def test_gemini_truncation_raises():
    with pytest.raises(LLMError, match="truncated"):
        _provider(lambda r: _reply(GOOD, finish="MAX_TOKENS")).understand_document(_content(), [])


def test_gemini_timeout_raises():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError, match="timed out"):
        _provider(handler).understand_document(_content(), [])


# ---------------------------------------------------------------- free-tier rate limits
def test_gemini_waits_for_per_minute_limit_then_succeeds():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return _rate_limited("GenerateRequestsPerMinutePerProjectPerModel-FreeTier") if len(calls) == 1 else _reply(GOOD)

    result, _ = _provider(handler, sleeps).understand_document(_content(), [])
    assert result.document_type == "gst_certificate"
    assert len(calls) == 2 and sleeps == [7.0]  # waited exactly as long as Google asked


def test_gemini_gives_up_after_repeated_rate_limits():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return _rate_limited("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", delay="500s")

    with pytest.raises(LLMError, match="rate limit"):
        _provider(handler, sleeps).understand_document(_content(), [])
    assert len(calls) == 3 and sleeps == [60.0, 60.0]  # two retries, each wait capped at 60 s


def test_gemini_daily_quota_fails_fast():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return _rate_limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier", delay="30s")

    with pytest.raises(LLMError, match="daily"):
        _provider(handler, sleeps).understand_document(_content(), [])
    assert len(calls) == 1 and sleeps == []  # no point waiting for tomorrow


def test_quota_details_tolerates_unexpected_bodies():
    class Exc:
        details = ["not a dict"]

    assert quota_details(Exc()) == (False, None)


def test_rate_limiter_paces_to_the_per_minute_limit():
    now, sleeps = [0.0], []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(clock=lambda: now[0], sleep=sleep)
    assert [limiter.wait(2) for _ in range(2)] == [0.0, 0.0]  # a burst up to the limit goes straight through
    assert limiter.wait(2) == 60.0  # the third request in the same minute waits for the window
    now[0] += 61
    assert limiter.wait(2) == 0.0
    assert limiter.wait(0) == 0.0  # 0 = pacing off (paid tier)


def test_gemini_retries_without_thinking_level_if_rejected():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("thinkingConfig" in body["generationConfig"])
        if "thinkingConfig" in body["generationConfig"]:
            return _error(400, "INVALID_ARGUMENT", "Thinking level is not supported for this model.")
        return _reply(GOOD)

    provider = _provider(handler)
    provider.understand_document(_content(), [])
    provider.understand_document(_content(), [])
    assert calls == [True, False, False] and provider.no_thinking == {MODEL}  # asked once, remembered for the run


# ---------------------------------------------------------------- backup models (free-tier 503 "high demand")
BACKUP = "gemini-3.1-flash-lite"
HIGH_DEMAND = "This model is currently experiencing high demand. Spikes in demand are usually temporary."


def _model_of(request) -> str:
    return re.search(r"/models/([^:/]+):generateContent", str(request.url)).group(1)


def _routed(answers, calls):
    """Handler that answers per model: answers[model] is a list of responses, the last one repeats."""
    def handler(request):
        model = _model_of(request)
        calls.append(model)
        queue = answers[model]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(reply):
            return reply()
        return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)  # a fresh copy
    return handler


def _good(model):
    return lambda: _reply(GOOD, modelVersion=model)


def test_busy_model_hands_over_to_the_backup_which_then_goes_first():
    calls, sleeps = [], []
    provider = _provider(_routed({MODEL: [_error(503, "UNAVAILABLE", HIGH_DEMAND)], BACKUP: [_good(BACKUP)]}, calls),
                         sleeps, fallbacks=[BACKUP])
    result, usage = provider.understand_document(_content(), [])
    assert result.document_type == "gst_certificate" and usage.model == BACKUP  # the model that answered is recorded
    provider.understand_document(_content(), [])
    assert calls == [MODEL, BACKUP, BACKUP] and sleeps == []  # no waiting, and the busy model is not asked again


def test_when_every_model_is_busy_it_pauses_and_tries_again():
    calls, sleeps = [], []
    busy = _error(503, "UNAVAILABLE", HIGH_DEMAND)
    provider = _provider(_routed({MODEL: [busy, _good(MODEL)], BACKUP: [busy]}, calls), sleeps, fallbacks=[BACKUP])
    _, usage = provider.understand_document(_content(), [])
    assert calls == [MODEL, BACKUP, MODEL] and sleeps == [5.0] and usage.model == MODEL


def test_gives_up_with_the_reason_when_every_model_stays_busy():
    calls, sleeps = [], []
    busy = _error(503, "UNAVAILABLE", HIGH_DEMAND)
    provider = _provider(_routed({MODEL: [busy], BACKUP: [busy]}, calls), sleeps, fallbacks=[BACKUP])
    with pytest.raises(LLMError, match="503.*high demand.*tried 2 Gemini models, 3 times"):
        provider.understand_document(_content(), [])
    assert len(calls) == 6 and sleeps == [5.0, 5.0]


def test_per_minute_limit_moves_to_the_backup_instead_of_waiting():
    calls, sleeps = [], []
    limited = _rate_limited("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", delay="40s")
    provider = _provider(_routed({MODEL: [limited], BACKUP: [_good(BACKUP)]}, calls), sleeps, fallbacks=[BACKUP])
    provider.understand_document(_content(), [])
    assert calls == [MODEL, BACKUP] and sleeps == []


@pytest.mark.parametrize("gone", [
    _rate_limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    _error(404, "NOT_FOUND", "This model is no longer available to new users."),
], ids=["daily-quota", "retired"])
def test_a_model_that_cannot_answer_today_is_skipped_for_the_rest_of_the_run(gone):
    calls = []
    provider = _provider(_routed({MODEL: [gone], BACKUP: [_good(BACKUP)]}, calls), fallbacks=[BACKUP])
    provider.understand_document(_content(), [])
    provider.current = MODEL  # even if asked to start with it again, it stays out
    provider.understand_document(_content(), [])
    assert calls == [MODEL, BACKUP, BACKUP]


def test_backups_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", f" {BACKUP}, {MODEL} ,gemini-3.5-flash")
    assert config.gemini_fallback_models() == [BACKUP, MODEL, "gemini-3.5-flash"]
    client = genai.Client(api_key="k", http_options=types.HttpOptions(httpx_client=httpx.Client(
        transport=httpx.MockTransport(lambda r: _reply(GOOD)))))
    assert GeminiProvider(MODEL, client=client).models == [MODEL, BACKUP, "gemini-3.5-flash"]  # main first, no repeats
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "none")
    assert config.gemini_fallback_models() == []


def test_happy_path_is_approved_while_the_main_model_is_overloaded(fresh_db):
    fake = _fake_gemini_with()

    def handler(request):
        return _error(503, "UNAVAILABLE", HIGH_DEMAND) if _model_of(request) == MODEL else fake(request)

    results = run_scenario("happy", provider=_provider(handler, fallbacks=[BACKUP]))
    assert all(r["ok"] for r in results), results
    sub = get_submission(db.query_one("SELECT id FROM submissions ORDER BY submitted_at DESC")["id"])
    assert sub["status"] == "APPROVED" and "DOC-004" not in {f["rule_id"] for f in sub["findings"]}


def test_gemini_other_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return _error(403, "PERMISSION_DENIED", "API key not valid")

    with pytest.raises(LLMError, match="403"):
        _provider(handler).understand_document(_content(), [])
    assert len(calls) == 1


# ---------------------------------------------------------------- provider selection
@pytest.fixture
def no_keys(monkeypatch):
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_auto_selection_prefers_claude_then_gemini_then_offline(no_keys):
    assert config.llm_provider_name() == "offline"
    no_keys.setenv("GEMINI_API_KEY", "g-key")
    assert config.llm_provider_name() == "gemini" and config.llm_model() == MODEL
    no_keys.setenv("ANTHROPIC_API_KEY", "a-key")
    assert config.llm_provider_name() == "anthropic" and config.llm_model() == "claude-sonnet-5-5"
    no_keys.setenv("LLM_PROVIDER", "gemini")
    assert config.llm_provider_name() == "gemini"


def test_each_provider_has_its_own_model_setting(no_keys):
    no_keys.setenv("LLM_MODEL", "claude-opus-5-5")
    no_keys.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    assert config.llm_model("anthropic") == "claude-opus-5-5"
    assert config.llm_model("gemini") == "gemini-3.6-flash"


def test_get_provider_builds_gemini_from_the_key(no_keys):
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        get_provider("gemini")
    no_keys.setenv("GEMINI_API_KEY", "g-key")
    provider = get_provider()
    assert isinstance(provider, GeminiProvider) and provider.model == MODEL


# ---------------------------------------------------------------- every scenario through the Gemini code path
def _fake_gemini_with(date_style=None):
    """A stand-in model that reads exactly what the offline rules read (no network, deterministic).

    date_style(field_name, iso) -> str rewrites date fields the way a real model sometimes does
    (echoing the printed form instead of YYYY-MM-DD).
    """
    def handler(request):
        body = json.loads(request.content)
        system = body["systemInstruction"]["parts"][0]["text"]
        parts = body["contents"][0]["parts"]
        if system.startswith("You read documents"):
            match = re.search(r"<document[^>]*>\n(.*)\n</document>", parts[0].get("text", ""), re.S)
            content = DocumentContent(filename="upload", sha256="", kind="pdf", text=match.group(1) if match else "")
            result = OfflineProvider().understand_document(content, [])[0].model_dump()
            if date_style:
                for f in result["fields"]:
                    if f["name"] in DATE_FIELDS and f["value"]:
                        f["value"] = date_style(f["name"], f["value"])
            return _reply(result)
        if system.startswith("You compare"):
            return _reply({"same_entity": "unsure", "reason": "not certain"})
        payload = json.loads(re.search(r"<outcome>\n(.*)\n</outcome>", parts[0]["text"], re.S).group(1))
        return _reply(comms.template_email(payload).model_dump())
    return handler


def _long_form(name, iso):  # "2026-08-13" -> "13 August 2026": unambiguous, but not ISO
    return datetime.date.fromisoformat(iso).strftime("%d %B %Y")


@pytest.mark.parametrize("scenario", [s["id"] for s in list_scenarios()])
@pytest.mark.parametrize("date_style", [None, _long_form], ids=["iso-dates", "printed-dates"])
def test_every_scenario_runs_through_the_gemini_code_path(fresh_db, scenario, date_style):
    results = run_scenario(scenario, provider=_provider(_fake_gemini_with(date_style)))
    assert all(r["ok"] for r in results), results
    calls = db.query("SELECT provider, model, input_tokens FROM llm_calls")
    assert calls and all(c["provider"] == "gemini" and c["model"] == MODEL and c["input_tokens"] for c in calls)
    # Screens and emails name the provider, never the model ID (that stays in llm_calls).
    shown = [r["drafted_by"] for r in db.query("SELECT drafted_by FROM outbox")]
    shown += [r["summary"] for r in db.query("SELECT summary FROM stage_runs")]
    assert not [s for s in shown if MODEL in s]


# ---------------------------------------------------------------- dates are normalised, never skipped
def _happy_with_letter_date(value):
    fake = _fake_gemini_with(lambda name, iso: value if name == "letter_date" else iso)
    run_scenario("happy", provider=_provider(fake))
    sub = get_submission(db.query_one("SELECT id FROM submissions ORDER BY submitted_at DESC")["id"])
    return sub, {f["rule_id"] for f in sub["findings"]}


def test_stale_bank_letter_is_caught_when_the_model_returns_a_printed_date(fresh_db):
    sub, rules = _happy_with_letter_date("01/01/2020")  # day-first, as printed on Indian letters
    assert "CON-008" in rules and sub["status"] != "APPROVED"


def test_unreadable_date_becomes_a_weak_field_not_a_silent_pass(fresh_db):
    sub, rules = _happy_with_letter_date("sometime last spring")
    assert "DOC-003" in rules and sub["status"] != "APPROVED"


def test_to_iso_date_formats():
    assert to_iso_date("13/08/2018") == "2018-08-13"
    assert to_iso_date("2018-08-13") == "2018-08-13"
    assert to_iso_date("13 August 2018") == to_iso_date("Aug 13, 2018") == "2018-08-13"
    assert to_iso_date("03/04/2026") == "2026-04-03"  # day first outside the US
    assert to_iso_date("03/04/2026", us_format=True) == "2026-03-04"
    assert to_iso_date("Date: 13.08.2018") == "2018-08-13"
    assert to_iso_date("last spring") == ""


def test_ordinals_and_the_document_decides_month_first():
    assert to_iso_date("2nd October 2026") == to_iso_date("02-Oct-2026") == "2026-10-02"
    assert month_first("bank_letter", {"routing_number": "021000021"}) is True  # US letter, even for a non-US vendor
    assert month_first("w9", {}) is True
    assert month_first("bank_letter", {"ifsc": "HDFC0001234"}, country="US") is False  # an Indian letter is day-first
    assert month_first("incorporation_certificate", {}, country="US") is True  # no markers: declared country decides


def test_us_bank_letter_date_is_read_month_first():
    # The case a live eval caught: "10/02/2026" on a US letter is 2 October, not 10 February.
    doc = DocResult(doc_id=1, slot="bank_proof", filename="letter.pdf", path="", sha256="", detected_type="bank_letter")
    doc.fields = {"routing_number": ExtractedField(name="routing_number", value="021000021", confidence=0.99, evidence=""),
                  "letter_date": ExtractedField(name="letter_date", value="10/02/2026", confidence=0.99, evidence="")}
    _normalise_dates(doc, us_format=month_first(doc.detected_type, {k: f.value for k, f in doc.fields.items()}))
    assert doc.value("letter_date") == "2026-10-02" and doc.fields["letter_date"].confidence == 0.99
