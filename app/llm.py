"""LLM provider config — OpenAI or any OpenAI-compatible API (Groq, etc.).

Resolution order:
  key   : OPENAI_API_KEY, then GROQ_API_KEY
  base  : LLM_BASE_URL, else api.openai.com or api.groq.com to match the key
  model : LLM_MODEL, else a sensible default per provider
"""

from __future__ import annotations

import os

_OPENAI_BASE = "https://api.openai.com/v1"
_GROQ_BASE = "https://api.groq.com/openai/v1"


def key() -> str | None:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")


def base() -> str:
    if os.environ.get("LLM_BASE_URL"):
        return os.environ["LLM_BASE_URL"].rstrip("/")
    return _OPENAI_BASE if os.environ.get("OPENAI_API_KEY") else _GROQ_BASE


def model() -> str:
    if os.environ.get("LLM_MODEL"):
        return os.environ["LLM_MODEL"]
    return "gpt-4o-mini" if os.environ.get("OPENAI_API_KEY") else "openai/gpt-oss-120b"


def enabled() -> bool:
    return bool(key())


def is_groq() -> bool:
    return "groq.com" in base()


def chat_extra() -> dict:
    """Provider quirks for /chat/completions bodies."""
    if is_groq():
        # gpt-oss models burn completion tokens on reasoning; keep it cheap.
        return {"reasoning_effort": "low"}
    return {}
