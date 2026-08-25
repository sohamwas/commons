"""One LLM code path, several providers.

Groq and OpenRouter are OpenAI-compatible, and Gemini exposes an OpenAI-compatible
endpoint, so a single client with per-role configuration covers the whole fleet. A
heterogeneous fleet is also more honest than four agents behind one model: a real
marketplace will not be single-vendor (handoff §16.2).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from commons.llm.cache import LLMCache, cache_key

load_dotenv(dotenv_path=".env")
logger = logging.getLogger(__name__)

PROVIDERS_PATH = Path(__file__).with_name("providers.yaml")


class LLMUnavailable(RuntimeError):
    """No key, or the provider refused. Callers fall back to deterministic behaviour."""


@dataclass
class ChatResult:
    text: str
    tool_calls: list = field(default_factory=list)
    cached: bool = False
    model: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0

    def json(self) -> dict | None:
        """Parse the reply as JSON, tolerating a ```json fence."""
        raw = self.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None


def load_config(path: Path = PROVIDERS_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class LLMClient:
    """A client bound to one role (an agent, or the persona engine)."""

    def __init__(
        self,
        role: str,
        cache: LLMCache | None = None,
        config: dict | None = None,
        offline: bool = False,
    ) -> None:
        cfg = config or load_config()
        if role not in cfg["roles"]:
            raise KeyError(f"no provider configured for role {role!r}")

        self.role = role
        spec = cfg["roles"][role]
        self.provider_name = spec["provider"]
        self.model = spec["model"]
        provider = cfg["providers"][self.provider_name]
        self.base_url = provider["base_url"]

        self.cache = cache if cache is not None else LLMCache()
        self.api_key = os.environ.get(provider["api_key_env"], "").strip()
        self.offline = offline or not self.api_key
        self._client: OpenAI | None = None

        if self.offline and not offline:
            logger.warning(
                "role %s has no key in %s — running offline", role, provider["api_key_env"]
            )

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key, base_url=self.base_url, max_retries=2, timeout=60.0
            )
        return self._client

    def chat(
        self,
        messages: list[dict],
        tools: list | None = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> ChatResult:
        payload = {
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        key = cache_key(self.role, self.model, payload)

        hit = self.cache.get(key)
        if hit is not None:
            self.cache.record_usage(self.role, self.model, 0, 0, cached=True)
            return ChatResult(
                text=hit.get("text", ""),
                tool_calls=hit.get("tool_calls", []),
                cached=True,
                model=self.model,
            )

        if self.offline:
            raise LLMUnavailable(f"{self.role}: no API key and no cached response")

        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            completion = self.client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — provider errors must not kill a run
            raise LLMUnavailable(f"{self.role} via {self.provider_name}: {exc}") from exc

        message = completion.choices[0].message
        calls = [
            {
                "id": c.id,
                "name": c.function.name,
                "arguments": c.function.arguments,
            }
            for c in (message.tool_calls or [])
        ]
        result = ChatResult(
            text=message.content or "",
            tool_calls=calls,
            cached=False,
            model=self.model,
            prompt_tokens=getattr(completion.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(completion.usage, "completion_tokens", 0) or 0,
        )

        self.cache.put(key, self.role, self.model, {"text": result.text, "tool_calls": calls})
        self.cache.record_usage(
            self.role, self.model, result.prompt_tokens, result.output_tokens, cached=False
        )
        return result
