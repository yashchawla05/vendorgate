"""Claude via the Anthropic Python SDK.

Reliability choices:
  * client = Anthropic(timeout=60s, max_retries=2): the SDK retries timeouts, 429 and 5xx
    with exponential backoff, so "2 retries with backoff" is the SDK's own behaviour.
  * client.messages.parse(output_format=<pydantic model>) constrains the reply to our schema
    and validates it locally; anything else raises LLMError and S3 marks the stage "degraded".
  * Refusals, truncation and missing output are errors too. We never fall back to "looks fine".
  * Server-side refusal fallbacks (Anthropic-recommended for Sonnet 5.5) are on by default;
    set LLM_REFUSAL_FALLBACK=off to disable.

The instructions themselves (and the prompt-injection stance) live in core/llm/prompts.py,
shared with the Gemini provider.
"""
from __future__ import annotations

import base64
import time

import anthropic
import pydantic

from core import config
from core.documents.reader import DocumentContent
from core.llm.base import LLMError, Usage
from core.llm.prompts import (DOC_SYSTEM, EMAIL_SYSTEM, NAME_SYSTEM, doc_task, document_text, email_input,
                              names_input)
from core.llm.schemas import DocumentUnderstanding, EmailDraft, NameVerdict

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic(timeout=60.0, max_retries=2)
        self.use_fallbacks = config.env("LLM_REFUSAL_FALLBACK", "on").lower() == "on"
        self.effort = config.env("LLM_EFFORT", "low")  # extraction is a simple task; low effort keeps it fast

    # ------------------------------------------------------------ core call
    def _parse(self, purpose: str, system: str, content: list[dict], output_format: type, max_tokens: int):
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": content}], output_format=output_format)
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        started = time.perf_counter()
        try:
            response = self._call(kwargs)
        except anthropic.APITimeoutError as exc:
            raise LLMError("LLM request timed out after retries") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the LLM API") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("LLM rate limit hit after retries") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"LLM API error {exc.status_code}: {exc.message}") from exc
        except pydantic.ValidationError as exc:
            raise LLMError(f"LLM output failed schema validation: {exc.error_count()} errors") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("LLM output was truncated")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("LLM returned no structured output")
        usage = Usage(provider=self.name, model=getattr(response, "model", self.model),
                      input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
                      latency_ms=int((time.perf_counter() - started) * 1000), purpose=purpose)
        return parsed, usage

    def _call(self, kwargs: dict):
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.parse(**kwargs, fallbacks="default", betas=[FALLBACK_BETA])
            except anthropic.BadRequestError as exc:
                if "fallback" not in str(exc).lower():
                    raise
                self.use_fallbacks = False  # this model/account does not support it; carry on without
        return self.client.messages.parse(**kwargs)

    # ------------------------------------------------------------ the three tasks
    def understand_document(self, content: DocumentContent, expected_types: list[str]) -> tuple[DocumentUnderstanding, Usage]:
        # Neither the slot (expected_types) nor the filename is sent: both are vendor claims and
        # would anchor the classification ("W9.pdf" may well be a PAN card). Code compares
        # the vendor's claim with the model's finding afterwards.
        blocks: list[dict] = []
        if content.has_text:
            blocks.append({"type": "text", "text": document_text(content.text)})
        elif content.images:
            for jpeg in content.images:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                           "data": base64.standard_b64encode(jpeg).decode()}})
        else:
            raise LLMError("Document has neither text nor images")
        blocks.append({"type": "text", "text": doc_task()})
        return self._parse("document", DOC_SYSTEM, blocks, DocumentUnderstanding, max_tokens=4000)

    def adjudicate_names(self, name_a: str, name_b: str, context: str) -> tuple[NameVerdict, Usage]:
        text = names_input(name_a, name_b, context)
        return self._parse("names", NAME_SYSTEM, [{"type": "text", "text": text}], NameVerdict, max_tokens=1000)

    def draft_email(self, payload: dict) -> tuple[EmailDraft, Usage]:
        text = email_input(payload)
        return self._parse("email", EMAIL_SYSTEM, [{"type": "text", "text": text}], EmailDraft, max_tokens=2000)
