"""Gemini via the Google Gen AI Python SDK (google-genai), Gemini Developer API with an AI Studio key.

Same three tasks, same instructions (core/llm/prompts.py) and same output schemas as the Claude
provider; only the transport differs. Reliability choices:
  * Timeout 60 s. The SDK retries timeouts, connection errors, 408, 500, 502 and 504 twice with
    exponential backoff (it retries nothing unless asked, so we ask).
  * Backup models (GEMINI_FALLBACK_MODELS). A busy model (503 "high demand", which the free tier
    sees often), a per-minute 429 or another 5xx sends the request straight to the next model, and
    the model that answered goes first for the rest of the run. Every model is the same Gemini
    family, given the same instructions and schemas; llm_calls records the model that answered.
    A daily quota used up, or a model Google has retired (404), takes that model out for the run.
  * When every model is busy or rate limited we wait (for the delay Google asks for, RetryInfo,
    capped at 60 s; 5 s when it is just busy) and try them all again, twice at most. Then LLMError.
  * A client-side limiter keeps this process under GEMINI_RPM requests per minute (default 10, the
    free-tier limit for Flash-Lite), so a scenario with many documents waits instead of failing.
    Set GEMINI_RPM=0 on a paid key to switch it off.
  * response_schema=<pydantic model> makes Gemini answer in our schema; we validate again locally.
    Blocked prompts, safety stops, truncation and invalid output raise LLMError, so S3 marks the
    stage "degraded" and the outcome is PENDING. We never fall back to "looks fine".
  * thinking_level (GEMINI_THINKING_LEVEL, default "low"). Thinking tokens count against the output
    limit, so the limits below leave room for them. A model that rejects the setting gets one retry
    without it.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Callable

import httpx
import pydantic
from google import genai
from google.genai import errors, types

from core import config
from core.documents.reader import DocumentContent
from core.llm.base import LLMError, Usage
from core.llm.prompts import (DOC_SYSTEM, EMAIL_SYSTEM, NAME_SYSTEM, doc_task, document_text, email_input,
                              names_input)
from core.llm.schemas import DocumentUnderstanding, EmailDraft, NameVerdict

SDK_RETRY_CODES = [408, 500, 502, 504]  # 429 and 503 are handled by GeminiProvider itself (next model first)
RETRY_ROUNDS = 2         # extra passes over all models when every one of them was busy or rate limited
MAX_WAIT_SECONDS = 60.0
BUSY_WAIT_SECONDS = 5.0  # pause before the next pass when every model answered 5xx
THINKING_LEVELS = {"MINIMAL", "LOW", "MEDIUM", "HIGH"}
DECLINED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE",
            "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION"}


class RateLimiter:
    """Sliding one-minute window, shared by every Gemini call in this process (all Streamlit sessions)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.clock, self.sleep = clock, sleep
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self, per_minute: int) -> float:
        """Block until one more request fits in the last 60 s; return the seconds waited."""
        if per_minute <= 0:
            return 0.0
        waited = 0.0
        with self.lock:
            while True:
                now = self.clock()
                while self.calls and now - self.calls[0] >= 60:
                    self.calls.popleft()
                if len(self.calls) < per_minute:
                    self.calls.append(now)
                    return waited
                pause = 60 - (now - self.calls[0])
                self.sleep(pause)
                waited += pause


LIMITER = RateLimiter()


def http_options(timeout_seconds: int = 60) -> types.HttpOptions:
    return types.HttpOptions(timeout=timeout_seconds * 1000,
                             retry_options=types.HttpRetryOptions(attempts=3, http_status_codes=SDK_RETRY_CODES))


def quota_details(exc: errors.APIError) -> tuple[bool, float | None]:
    """From a 429 body: (is it the daily quota?, seconds Google asks us to wait)."""
    body = exc.details if isinstance(exc.details, dict) else {}
    daily, delay = False, None
    for item in (body.get("error") or {}).get("details") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            daily = daily or any("perday" in str(v.get("quotaId", "")).lower()
                                 for v in item.get("violations") or [] if isinstance(v, dict))
        elif kind.endswith("RetryInfo"):
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(item.get("retryDelay", "")))
            if match:
                delay = float(match.group(1))
    return daily, delay


def _name(value) -> str:
    """Enum or string from the SDK as a plain upper-case name ('' when missing)."""
    return str(getattr(value, "value", value) or "").upper()


class _Busy(Exception):
    """This model cannot answer right now; another model, or this one a little later, may."""

    def __init__(self, message: str, wait: float):
        super().__init__(message)
        self.wait = wait


class _Out(Exception):
    """This model cannot answer for the rest of the run (daily quota used up, model retired)."""


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str, client: genai.Client | None = None, limiter: RateLimiter = LIMITER,
                 sleep: Callable[[float], None] = time.sleep, fallbacks: list[str] | None = None):
        self.model = model
        if client is None:
            if not config.gemini_api_key():
                raise LLMError("GEMINI_API_KEY is not set")
            client = genai.Client(api_key=config.gemini_api_key(), http_options=http_options())
        self.client = client
        self.limiter, self.sleep = limiter, sleep
        self.per_minute = int(config.env("GEMINI_RPM", "10"))
        level = config.env("GEMINI_THINKING_LEVEL", "low").strip().upper()
        self.thinking_level = level if level in THINKING_LEVELS else ""  # extraction is simple; low keeps it fast
        backups = config.gemini_fallback_models() if fallbacks is None else fallbacks
        self.models = list(dict.fromkeys([model, *backups]))
        self.current = model          # the model that answered last goes first
        self.out: dict[str, str] = {}  # model -> why it is out for the rest of this run
        self.no_thinking: set[str] = set()

    # ------------------------------------------------------------ core call
    def _config(self, model: str, system: str, schema: type, max_tokens: int) -> types.GenerateContentConfig:
        settings = dict(system_instruction=system, response_mime_type="application/json", response_schema=schema,
                        max_output_tokens=max_tokens)
        if self.thinking_level and model not in self.no_thinking:
            settings["thinking_config"] = types.ThinkingConfig(thinking_level=self.thinking_level)
        return types.GenerateContentConfig(**settings)

    def _order(self) -> list[str]:
        usable = [m for m in self.models if m not in self.out]
        return sorted(usable, key=lambda m: m != self.current)  # stable: the rest keep their configured order

    def _call(self, model: str, system: str, parts: list, schema: type, max_tokens: int):
        self.limiter.wait(self.per_minute)
        try:
            return self.client.models.generate_content(model=model, contents=parts,
                                                       config=self._config(model, system, schema, max_tokens))
        except errors.ClientError as exc:
            if exc.code == 429:
                daily, delay = quota_details(exc)
                if daily:
                    raise _Out("Gemini daily request quota used up (free tier resets at midnight Pacific time)") from exc
                raise _Busy("LLM rate limit hit after retries",
                            min(delay if delay is not None else 10.0, MAX_WAIT_SECONDS)) from exc
            if exc.code == 400 and self.thinking_level and model not in self.no_thinking \
                    and "thinking" in str(exc.message or "").lower():
                self.no_thinking.add(model)  # this model does not take a thinking level; carry on without
                return self._call(model, system, parts, schema, max_tokens)
            if exc.code == 404:
                raise _Out(f"LLM API error 404: {exc.message}") from exc
            raise LLMError(f"LLM API error {exc.code}: {exc.message}") from exc
        except errors.ServerError as exc:  # 503 "high demand" at once, other 5xx after the SDK's retries
            raise _Busy(f"LLM API error {exc.code}: {exc.message}", BUSY_WAIT_SECONDS) from exc
        except errors.APIError as exc:
            raise LLMError(f"LLM API error {exc.code}: {exc.message}") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("LLM request timed out after retries") from exc
        except httpx.TransportError as exc:
            raise LLMError("Could not reach the LLM API") from exc

    def _generate(self, purpose: str, system: str, parts: list, schema: type, max_tokens: int):
        started = time.perf_counter()
        busy: list[_Busy] = []
        for attempt in range(RETRY_ROUNDS + 1):
            if attempt:
                self.sleep(min(b.wait for b in busy))
            busy = []
            for model in self._order():
                try:
                    response = self._call(model, system, parts, schema, max_tokens)
                except _Busy as exc:
                    busy.append(exc)
                    continue
                except _Out as exc:
                    self.out[model] = str(exc)
                    continue
                self.current = model
                parsed = self._validated(response, schema)
                meta = response.usage_metadata
                usage = Usage(provider=self.name, model=response.model_version or model,
                              input_tokens=(meta.prompt_token_count or 0) if meta else 0,
                              output_tokens=((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
                              if meta else 0,
                              latency_ms=int((time.perf_counter() - started) * 1000), purpose=purpose)
                return parsed, usage
            if not busy:  # nothing left to wait for: every model is out for this run
                raise LLMError("; ".join(dict.fromkeys(self.out.values())) or "No Gemini model configured")
        tried = f" (tried {len(self._order())} Gemini models, {RETRY_ROUNDS + 1} times)" if len(self._order()) > 1 else ""
        raise LLMError(f"{busy[-1]}{tried}")

    @staticmethod
    def _validated(response: types.GenerateContentResponse, schema: type):
        feedback = response.prompt_feedback
        if feedback is not None and _name(feedback.block_reason):
            raise LLMError(f"The model declined this request (blocked: {_name(feedback.block_reason)})")
        if not response.candidates:
            raise LLMError("LLM returned no candidates")
        reason = _name(response.candidates[0].finish_reason)
        if reason == "MAX_TOKENS":
            raise LLMError("LLM output was truncated")
        if reason in DECLINED:
            raise LLMError(f"The model declined this request ({reason})")
        if reason not in ("", "STOP"):
            raise LLMError(f"LLM stopped early: {reason}")
        if isinstance(response.parsed, schema):
            return response.parsed
        text = response.text  # the SDK leaves .parsed empty when validation fails; say why
        if not text:
            raise LLMError("LLM returned no structured output")
        try:
            return schema.model_validate_json(text)
        except pydantic.ValidationError as exc:
            raise LLMError(f"LLM output failed schema validation: {exc.error_count()} errors") from exc

    # ------------------------------------------------------------ the three tasks
    def understand_document(self, content: DocumentContent, expected_types: list[str]) -> tuple[DocumentUnderstanding, Usage]:
        # As with Claude, neither the slot (expected_types) nor the filename is sent: both are vendor
        # claims and would anchor the classification. Code compares claim and finding afterwards.
        if content.has_text:
            parts = [types.Part.from_text(text=document_text(content.text))]
        elif content.images:
            parts = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg") for jpeg in content.images]
        else:
            raise LLMError("Document has neither text nor images")
        parts.append(types.Part.from_text(text=doc_task()))
        return self._generate("document", DOC_SYSTEM, parts, DocumentUnderstanding, max_tokens=8000)

    def adjudicate_names(self, name_a: str, name_b: str, context: str) -> tuple[NameVerdict, Usage]:
        parts = [types.Part.from_text(text=names_input(name_a, name_b, context))]
        return self._generate("names", NAME_SYSTEM, parts, NameVerdict, max_tokens=2000)

    def draft_email(self, payload: dict) -> tuple[EmailDraft, Usage]:
        parts = [types.Part.from_text(text=email_input(payload))]
        return self._generate("email", EMAIL_SYSTEM, parts, EmailDraft, max_tokens=4000)
