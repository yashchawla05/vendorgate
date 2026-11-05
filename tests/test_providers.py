"""Document understanding: offline provider on real files, Anthropic provider against a mock HTTP server.

The Anthropic tests never touch the network: the SDK is given an httpx2 MockTransport,
so we can test request shape, schema validation and failure handling for free.
"""
import json

import anthropic
import httpx2
import pytest

from core.config import DATA_DIR, SCENARIO_DIR
from core.documents.injection import find_injection
from core.documents.reader import read_document
from core.llm.anthropic_provider import AnthropicProvider
from core.llm.base import LLMError
from core.llm.offline_provider import OfflineProvider, classify


# ---------------------------------------------------------------- offline
def test_offline_reads_gst_certificate():
    content = read_document(SCENARIO_DIR / "happy" / "initial" / "gst_certificate.pdf")
    result, usage = OfflineProvider().understand_document(content, ["gst_certificate"])
    fields = {f.name: f for f in result.fields}
    assert result.document_type == "gst_certificate" and result.type_confidence >= 0.9
    assert fields["legal_name"].value == "Kestrel Analytics Private Limited"
    assert fields["gstin"].confidence >= 0.8 and fields["gstin"].evidence
    assert usage.input_tokens == 0


def test_offline_detects_pan_card_in_w9_slot():
    content = read_document(SCENARIO_DIR / "e2_wrong_docs" / "initial" / "w9.pdf")
    result, _ = OfflineProvider().understand_document(content, ["w9"])
    assert result.document_type == "pan_card"


def test_offline_marks_scan_unreadable():
    content = read_document(DATA_DIR / "samples" / "scanned_pan_card.jpg")
    assert not content.has_text and content.images
    result, _ = OfflineProvider().understand_document(content, ["pan_card"])
    assert not result.readable


def test_classifier_unknown_text_is_other():
    assert classify("Quarterly newsletter about gardening")[0] == "other"


def test_injection_detector():
    text = (DATA_DIR / "history" / "H16" / "bank_proof.pdf")
    hits = find_injection(read_document(text).text)
    assert hits and "ignore all previous instructions" in hits[0].lower()
    assert find_injection("This is to confirm that the following account is maintained with us") == []


def test_unsupported_file_type(tmp_path):
    path = tmp_path / "doc.docx"
    path.write_bytes(b"not a pdf")
    assert "Unsupported" in read_document(path).error


# ---------------------------------------------------------------- anthropic (mocked HTTP)
GOOD = {
    "document_type": "gst_certificate", "type_confidence": 0.97, "readable": True,
    "fields": [{"name": "gstin", "value": "29ZZSCK1133Y1Z9", "confidence": 0.98, "evidence": "Registration Number 29ZZSCK1133Y1Z9"}],
    "suspicious_instructions": False, "notes": "",
}


def _message(text: str, stop_reason: str = "end_turn") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 150}}


def _provider(handler) -> AnthropicProvider:
    client = anthropic.Anthropic(api_key="test-key", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return AnthropicProvider(model="claude-sonnet-5-5", client=client)


def _content():
    return read_document(SCENARIO_DIR / "happy" / "initial" / "gst_certificate.pdf")


def test_anthropic_parses_structured_output_and_counts_tokens():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_message(json.dumps(GOOD)))

    result, usage = _provider(handler).understand_document(_content(), ["gst_certificate"])
    assert result.document_type == "gst_certificate"
    assert usage.input_tokens == 1200 and usage.output_tokens == 150
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert "untrusted" in body["system"]  # injection stance is in the system prompt
    user_text = body["messages"][0]["content"][0]["text"]
    assert user_text.startswith("<document") and "Kestrel Analytics" in user_text
    assert "gst_certificate" not in user_text.split("</document>")[0]  # no slot hint leaks into the data
    assert body["output_config"]["format"]["type"] == "json_schema"


def test_anthropic_schema_violation_raises():
    bad = dict(GOOD, document_type="passport")  # not an allowed enum value
    provider = _provider(lambda r: httpx2.Response(200, json=_message(json.dumps(bad))))
    with pytest.raises(LLMError):
        provider.understand_document(_content(), [])


def test_anthropic_server_error_raises():
    provider = _provider(lambda r: httpx2.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}}))
    with pytest.raises(LLMError, match="500"):
        provider.understand_document(_content(), [])


def test_anthropic_refusal_raises():
    # Depending on what a refusal carries, the SDK fails schema validation first or we see
    # stop_reason == "refusal". Either way it must become an LLMError (stage degraded).
    provider = _provider(lambda r: httpx2.Response(200, json=_message("{}", stop_reason="refusal")))
    with pytest.raises(LLMError):
        provider.understand_document(_content(), [])
    ok_but_refused = _provider(lambda r: httpx2.Response(200, json=_message(json.dumps(GOOD), stop_reason="refusal")))
    with pytest.raises(LLMError, match="declined"):
        ok_but_refused.understand_document(_content(), [])


def test_anthropic_retries_without_fallbacks_if_rejected():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("fallbacks" in body)
        if "fallbacks" in body:
            return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                          "message": "fallbacks not supported"}})
        return httpx2.Response(200, json=_message(json.dumps(GOOD)))

    provider = _provider(handler)
    provider.understand_document(_content(), [])
    assert calls == [True, False] and provider.use_fallbacks is False


def test_anthropic_sends_images_for_scans():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_message(json.dumps(dict(GOOD, document_type="pan_card", fields=[]))))

    _provider(handler).understand_document(read_document(DATA_DIR / "samples" / "scanned_pan_card.jpg"), [])
    first = seen["body"]["messages"][0]["content"][0]
    assert first["type"] == "image" and first["source"]["media_type"] == "image/jpeg"
