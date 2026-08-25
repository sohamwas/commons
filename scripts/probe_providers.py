"""Probe each free-tier LLM provider for real, account-specific limits.

Prints ONLY: whether a key is present, model availability, tool-calling support,
and rate-limit response headers. Never prints key material.

Run:  .venv/Scripts/python.exe scripts/probe_providers.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDERS = {
    "groq": {
        "env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "prefer": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen"],
    },
    "cerebras": {
        "env": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "prefer": ["llama-3.3-70b", "llama3.3-70b", "qwen"],
    },
    "gemini": {
        "env": "GOOGLE_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "prefer": ["flash-lite", "flash"],
    },
    "openrouter": {
        "env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "prefer": [":free"],
    },
}

# Minimal tool-calling probe: cheapest possible request that still proves the
# model can emit a structured tool call, which is what the agents depend on.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Reply to a ping.",
            "parameters": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
    }
]
MESSAGES = [{"role": "user", "content": "Call the ping tool with ok=true."}]

RATELIMIT_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after", "x-request-id")


def pick_model(available: list[str], prefer: list[str]) -> str | None:
    for token in prefer:
        for name in available:
            if token in name:
                return name
    return available[0] if available else None


def probe(name: str, cfg: dict) -> None:
    print(f"\n{'=' * 62}\n{name.upper()}\n{'=' * 62}")

    key = os.environ.get(cfg["env"], "").strip()
    if not key:
        print(f"  SKIP: {cfg['env']} not set")
        return
    print(f"  key: present ({len(key)} chars)")

    client = OpenAI(api_key=key, base_url=cfg["base_url"], max_retries=0, timeout=45.0)

    # ---- 1. what models does this account actually see? ----
    try:
        models = sorted(m.id for m in client.models.list().data)
        print(f"  models visible: {len(models)}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"  models.list FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        models = []

    model = pick_model(models, cfg["prefer"])
    if not model:
        print("  no usable model found; skipping generation probe")
        return
    print(f"  probing with: {model}")

    # ---- 2. one real tool-calling request; capture rate-limit headers ----
    try:
        raw = client.chat.completions.with_raw_response.create(
            model=model,
            messages=MESSAGES,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=64,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"  generation FAILED: {type(exc).__name__}: {str(exc)[:300]}")
        return

    completion = raw.parse()
    calls = completion.choices[0].message.tool_calls
    print(f"  tool calling: {'OK -> ' + calls[0].function.name if calls else 'NO TOOL CALL EMITTED'}")
    if completion.usage:
        u = completion.usage
        print(f"  usage: prompt={u.prompt_tokens} completion={u.completion_tokens} total={u.total_tokens}")

    limits = {
        k: v
        for k, v in raw.headers.items()
        if any(k.lower().startswith(p) for p in RATELIMIT_PREFIXES)
    }
    if limits:
        print("  rate-limit headers:")
        for k in sorted(limits):
            print(f"    {k}: {limits[k]}")
    else:
        print("  rate-limit headers: none returned")


def openrouter_key_status() -> None:
    """OpenRouter exposes authoritative per-key limits at /api/v1/key."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return
    import httpx2 as httpx

    print(f"\n{'=' * 62}\nOPENROUTER /api/v1/key (authoritative)\n{'=' * 62}")
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30.0,
        )
        data = r.json().get("data", {})
        for field in ("label", "usage", "limit", "limit_remaining", "is_free_tier", "rate_limit"):
            if field in data:
                print(f"  {field}: {data[field]}")
        if not data:
            print(f"  unexpected response: {str(r.text)[:300]}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"  FAILED: {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    only = sys.argv[1:] or list(PROVIDERS)
    for pname in only:
        if pname in PROVIDERS:
            probe(pname, PROVIDERS[pname])
    openrouter_key_status()
    print()
