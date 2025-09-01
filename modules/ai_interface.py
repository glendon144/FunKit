"""AI Interface module for PiKit

This module wraps OpenAI-compatible chat-completions endpoints (e.g., Baseten,
OpenAI, local llama.cpp servers that emulate the API) and provides a stable
surface for the rest of the app.

- Compatible with openai>=1.0.0
- Respects provider_switch.resolve_endpoint()/model_name()/whoami()
- Offers convenient .query(), .stream_query(), and .quick_ask() helpers
"""

from __future__ import annotations

from typing import Iterable, Generator, Optional, List, Tuple, Any, Dict
import os
import re

# --- Provider switch integration (tolerate absence at import time) ---
try:
    from modules.provider_switch import resolve_endpoint, model_name, whoami  # type: ignore
except Exception:  # pragma: no cover
    def resolve_endpoint() -> Tuple[str, Dict[str,str]]:  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY", "") or os.getenv("BASE10_API_KEY", "")
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return base, headers
    def model_name() -> str:  # type: ignore
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    def whoami() -> str:  # type: ignore
        return "env-default"

# --- OpenAI client (v1) ---
from openai import OpenAI
from openai._exceptions import APIError, RateLimitError, APITimeoutError, APIConnectionError


def _extract_api_key(headers: Dict[str, str]) -> Optional[str]:
    """Pull a Bearer token out of headers, if present."""
    auth = headers.get("Authorization") or headers.get("authorization")
    if not auth:
        return None
    m = re.match(r"Bearer\s+(.+)", auth.strip(), re.I)
    return m.group(1) if m else None


class AIInterface:
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 512

    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        # Resolve provider first
        prov_url, prov_headers = resolve_endpoint()
        if base_url is None:
            base_url = prov_url.rsplit("/chat/completions", 1)[0]
        key_from_headers = _extract_api_key(prov_headers)
        api_key = api_key or key_from_headers or os.getenv("OPENAI_API_KEY") or ""

        # Instantiate OpenAI client
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)  # type: ignore[arg-type]
        self.model = model or model_name()

    # -------- Low-level wrappers --------

    def chat(self,
             messages: List[dict],
             *,
             model: Optional[str] = None,
             temperature: float = DEFAULT_TEMPERATURE,
             top_p: float = 1.0,
             max_tokens: int = DEFAULT_MAX_TOKENS,
             presence_penalty: float = 0.0,
             frequency_penalty: float = 0.0,
             stop: Optional[Iterable[str]] = None,
             extra: Optional[dict] = None) -> str:
        """Blocking call that returns the final assistant message string."""
        kwargs: Dict[str, Any] = dict(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
        )
        if stop:
            kwargs["stop"] = list(stop)
        if extra:
            kwargs.update(extra)

        try:
            resp = self.client.chat.completions.create(**kwargs)
            # Prefer the assistant message content
            return (resp.choices[0].message.content or "").strip()
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            raise
        except APIError as e:
            raise

    def stream(self,
               messages: List[dict],
               *,
               model: Optional[str] = None,
               temperature: float = DEFAULT_TEMPERATURE,
               top_p: float = 1.0,
               max_tokens: int = DEFAULT_MAX_TOKENS,
               presence_penalty: float = 0.0,
               frequency_penalty: float = 0.0,
               stop: Optional[Iterable[str]] = None,
               include_usage: bool = True,
               continuous_usage_stats: bool = True,
               extra: Optional[dict] = None) -> Generator[str, None, None]:
        """Streaming generator that yields content deltas as they arrive."""
        kwargs: Dict[str, Any] = dict(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
            stream=True,
            stream_options={
                "include_usage": include_usage,
                "continuous_usage_stats": continuous_usage_stats,
            },
        )
        if stop:
            kwargs["stop"] = list(stop)
        if extra:
            kwargs.update(extra)

        opener = self.client.chat.completions.create
        resp = opener(**kwargs)
        for chunk in resp:
            try:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
            except Exception:
                continue

    # -------- Convenience --------

    def quick_ask(self,
                  prompt: str,
                  *,
                  system: Optional[str] = None,
                  model: Optional[str] = None,
                  stream: bool = False,
                  **kw):
        messages: List[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if stream:
            return self.stream(messages=messages, model=model, **kw)
        return self.chat(messages=messages, model=model, **kw)

    # -------- Back-compat aliases --------
    def generate(self, *args, **kwargs):
        return self.chat(*args, **kwargs)

    def complete(self, *args, **kwargs):
        return self.chat(*args, **kwargs)

    def chat_stream(self, *args, **kwargs):
        return self.stream(*args, **kwargs)

    # -------- Back-compat entry points --------
    def query(self, *args, **kwargs):
        """Flexible entry point compatible with older callers.

        Forms:
            ai.query(messages=[...], stream=False, **kw)
            ai.query("prompt", stream=False, **kw)
            ai.query(prompt="...", stream=False, **kw)
        """
        # Normalize arguments
        stream = bool(kwargs.pop("stream", False))

        if args and isinstance(args[0], str) and "messages" not in kwargs:
            prompt = args[0]
            rest = args[1:]
            return self.quick_ask(prompt, stream=stream, **kwargs)

        messages = kwargs.get("messages")
        if messages is None and args:
            messages = args[0]
        if not isinstance(messages, list):
            raise TypeError("ai.query() expects a prompt string or messages=[...]")

        if stream:
            # Return a generator
            return self.stream(messages=messages, **kwargs)
        else:
            return self.chat(messages=messages, **kwargs)

    def stream_query(self, *args, **kwargs) -> Generator[str, None, None]:
        kwargs["stream"] = True
        gen = self.query(*args, **kwargs)
        if hasattr(gen, "__iter__") and not isinstance(gen, (str, bytes)):
            return gen  # type: ignore[return-value]

        def _one():
            yield str(gen)
        return _one()

    # -------- Optional helper for health checking --------
    def ping(self) -> dict:
        """Hit the provider's /models endpoint to verify connectivity."""
        import requests
        base, headers = resolve_endpoint()
        models_url = base.rsplit("/chat/completions", 1)[0] + "/models"
        r = requests.get(models_url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()


def make_default() -> AIInterface:
    return AIInterface()

