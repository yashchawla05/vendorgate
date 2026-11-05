"""The provider interface: the three places the pipeline uses language understanding.

  understand_document  - S3: classify an upload and extract fields with evidence
  adjudicate_names     - S5: only for borderline name pairs (fuzzy score 80-95)
  draft_email          - S9: wording of the vendor email from structured findings

Three implementations:
  AnthropicProvider  - Claude via the Anthropic SDK (used when ANTHROPIC_API_KEY is set)
  GeminiProvider     - Gemini via the Google Gen AI SDK (used when only GEMINI_API_KEY is set)
  OfflineProvider    - deterministic rules (keyword classifier, regex extraction, templates)
The two LLM providers share their instructions (prompts.py) and output schemas (schemas.py).

Swapping providers never changes a decision rule; it only changes how facts are read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from core.documents.reader import DocumentContent
from core.llm.schemas import DocumentUnderstanding, EmailDraft, NameVerdict


PROVIDER_LABELS = {"gemini": "Google Gemini", "anthropic": "Anthropic Claude", "offline": "built-in rules (offline)"}


def provider_label(name: str | None) -> str:
    """What screens and messages call a provider: its maker and family, never a model ID."""
    return PROVIDER_LABELS.get(name or "", name or "-")


class LLMError(Exception):
    """Raised when a provider cannot produce a valid result (timeout, schema error, refusal...)."""


@dataclass
class Usage:
    """Token accounting for one call (zero for the offline provider)."""

    provider: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    purpose: str = ""
    extra: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str

    def understand_document(self, content: DocumentContent, expected_types: list[str]) -> tuple[DocumentUnderstanding, Usage]: ...

    def adjudicate_names(self, name_a: str, name_b: str, context: str) -> tuple[NameVerdict, Usage]: ...

    def draft_email(self, payload: dict) -> tuple[EmailDraft, Usage]: ...


def get_provider(name: str | None = None) -> LLMProvider:
    from core import config

    choice = name or config.llm_provider_name()
    if choice == "anthropic":
        from core.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=config.llm_model("anthropic"))
    if choice == "gemini":
        from core.llm.gemini_provider import GeminiProvider

        return GeminiProvider(model=config.llm_model("gemini"))
    from core.llm.offline_provider import OfflineProvider

    return OfflineProvider()
