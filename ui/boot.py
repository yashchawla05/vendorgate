"""One-time startup work, shared by every page.

Streamlit re-runs scripts on every click, so anything expensive or stateful is
wrapped in st.cache_resource, which runs once per server process.
"""
import streamlit as st


@st.cache_resource(show_spinner="Preparing database…")
def _boot_once() -> dict:
    try:
        from core.seed import ensure_ready  # added in M4; absent in the M0 skeleton
    except ImportError:
        return {"seeded": False}
    return ensure_ready()


def boot() -> dict:
    return _boot_once()


def remember_base_url() -> None:
    """Resubmission links need the app's public URL. If APP_BASE_URL is not configured,
    take the origin of the current browser request (works on any host without setup)."""
    import os
    from urllib.parse import urlparse

    if os.environ.get("APP_BASE_URL", "").strip():
        return
    try:
        url = urlparse(st.context.url or "")
    except Exception:  # no browser context (tests, scripts)
        return
    if url.scheme and url.netloc:
        os.environ["APP_BASE_URL"] = f"{url.scheme}://{url.netloc}"
