"""Central configuration: paths and environment settings.

Everything that can differ between a laptop and the hosted app is read here,
so the rest of the code never touches os.environ directly.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # .env is a local-dev convenience; on the host, env vars come from secrets
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SCENARIO_DIR = DATA_DIR / "scenarios"
FORM_SAMPLE_DIR = DATA_DIR / "form_samples"
SANCTIONS_DIR = DATA_DIR / "sanctions"
REGISTRY_FILE = DATA_DIR / "registry" / "simulated_registry.json"
VENDOR_SEED_FILE = DATA_DIR / "vendor_master_seed.json"
HISTORY_DIR = DATA_DIR / "history"
EVAL_DIR = DATA_DIR / "eval"

# Runtime state lives in one folder that is safe to delete (free hosts wipe it anyway).
RUNTIME_DIR = DATA_DIR / "runtime"
UPLOAD_DIR = RUNTIME_DIR / "uploads"


def env(name: str, default: str = "") -> str:
    """Read an env var, treating empty strings as 'not set'."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


def db_path() -> Path:
    return Path(env("VG_DB_PATH", str(RUNTIME_DIR / "vendorgate.db")))


def gemini_api_key() -> str:
    return env("GEMINI_API_KEY")


def llm_provider_name() -> str:
    """'anthropic', 'gemini' or 'offline'. 'auto' picks the first one with a key: Anthropic, then Gemini."""
    choice = env("LLM_PROVIDER", "auto").lower()
    if choice == "auto":
        if env("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "gemini" if gemini_api_key() else "offline"
    return choice


def llm_model(provider: str | None = None) -> str:
    """Model ID for a provider: GEMINI_MODEL for Gemini, LLM_MODEL for Claude."""
    if (provider or llm_provider_name()) == "gemini":
        return env("GEMINI_MODEL", "gemini-3.5-flash-lite")
    return env("LLM_MODEL", "claude-sonnet-5-5")


def gemini_fallback_models() -> list[str]:
    """Gemini models tried, in order, when the main one is busy, rate limited or retired. 'none' = no backups."""
    value = env("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.5-flash")
    return [m.strip() for m in value.split(",") if m.strip() and m.strip().lower() != "none"]


def max_pages_per_doc() -> int:
    return int(env("LLM_MAX_PAGES_PER_DOC", "4"))


def max_docs_per_submission() -> int:
    return int(env("LLM_MAX_DOCS_PER_SUBMISSION", "8"))


def app_base_url() -> str:
    return env("APP_BASE_URL", "http://localhost:8501").rstrip("/")


def email_mode() -> str:
    return env("EMAIL_MODE", "simulated").lower()
