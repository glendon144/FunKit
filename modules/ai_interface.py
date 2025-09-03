#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ai_interface.py — normalized, Baseten-working version (with query()/ask() wrappers)

Key points:
- Uses OpenAI SDK with custom base_url for OpenAI-compatible providers (e.g., Baseten).
- Always sends Authorization: Bearer <token>.
- Ensures endpoint ends with /v1 and calls /chat/completions.
- Explicit, friendly errors when API key or model are missing.
- Optional streaming support.
- HTTP fallback (requests) with trust_env=False and proxies={} if SDK unavailable.
- Back-compat: .query(...) and .ask(...) wrap .chat(...)

Quick test:
  python3 -m modules.ai_interface --provider baseten --system "You are helpful." --user "Say hello in 3 words."
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Generator, Union

# Optional SDK import
try:
    # OpenAI >= 1.0 style client
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI = True
except Exception:
    OpenAI = None  # type: ignore
    _HAS_OPENAI = False

# Fallback HTTP
try:
    import requests  # type: ignore
    _HAS_REQUESTS = True
except Exception:
    requests = None  # type: ignore
    _HAS_REQUESTS = False


# ---------------------------
# Provider Configuration
# ---------------------------

@dataclass(frozen=True)
class ProviderConfig:
    key: str                     # short key, e.g. "baseten"
    label: str                   # human label
    base_url: str                # e.g. https://inference.baseten.co/v1
    env_var: str                 # environment variable for API key
    model: str                   # default model for this provider
    request_timeout: int = 60    # seconds


def _ensure_v1(url: str) -> str:
    """Normalize a provider base URL to end with '/v1' (no trailing slash)."""
    u = url.strip().rstrip("/")
    if not u.endswith("/v1"):
        u = f"{u}/v1"
    return u


# Baseten (OpenAI-compatible) default — adjust model if yours differs
DEFAULT_BASETEN_MODEL = os.getenv("BASETEN_DEFAULT_MODEL", "openai/gpt-oss-120b")

PROVIDERS: Dict[str, ProviderConfig] = {
    "baseten": ProviderConfig(
        key="baseten",
        label="Baseten (OpenAI compatible)",
        base_url=_ensure_v1(os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1")),
        env_var=os.getenv("BASETEN_ENV_VAR", "BASETEN_API_KEY"),
        model=os.getenv("BASETEN_MODEL", DEFAULT_BASETEN_MODEL),
        request_timeout=int(os.getenv("BASETEN_TIMEOUT", "60")),
    ),
    # Add additional OpenAI-compatible providers here if needed
}


# ---------------------------
# Exceptions
# ---------------------------

class AIInterfaceError(Exception):
    pass


# ---------------------------
# AI Interface
# ---------------------------

class AIInterface:
    """
    Normalized interface that uses the OpenAI SDK against an OpenAI-compatible endpoint
    (Baseten by default). Falls back to raw HTTP if SDK is unavailable.
    """

    def __init__(
        self,
        provider_key: str = "baseten",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_timeout: Optional[int] = None,
    ) -> None:
        if provider_key not in PROVIDERS:
            raise AIInterfaceError(
                f"Unknown provider '{provider_key}'. Available: {', '.join(PROVIDERS.keys())}"
            )

        self.provider = PROVIDERS[provider_key]

        # Choose model (CLI override > env/provider default)
        self.model = (model or self.provider.model).strip()
        if not self.model:
            raise AIInterfaceError(
                f"{self.provider.label}: model not configured. "
                f"Set env '{self.provider.env_var}' and/or provider default."
            )

        # API key (CLI override > env)
        self.api_key = api_key or os.getenv(self.provider.env_var, "").strip()
        if not self.api_key:
            raise AIInterfaceError(
                f"{self.provider.label}: API key missing. Expected env var '{self.provider.env_var}'."
            )

        # Base URL (CLI override > provider default), normalized to /v1
        self.base_url = _ensure_v1((base_url or self.provider.base_url).strip())
        self.request_timeout = int(request_timeout or self.provider.request_timeout)

        # Prepare SDK client if available
        self._client = None
        if _HAS_OPENAI:
            try:
                self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception as e:
                # Fall back to HTTP later
                sys.stderr.write(f"[ai_interface] OpenAI SDK init failed, will use HTTP fallback: {e}\n")
                self._client = None
        else:
            sys.stderr.write("[ai_interface] OpenAI SDK not installed; using HTTP fallback.\n")

    # -------------
    # Public API
    # -------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Union[str, Generator[str, None, None]]:
        """
        Send a Chat Completions request. Returns the full text (non-stream) or a generator of chunks (stream=True).
        messages: list like [{"role": "system"/"user"/"assistant", "content": "..."}]
        """

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        # Prefer SDK when possible
        if self._client is not None:
            if stream:
                return self._stream_sdk(payload)
            return self._nonstream_sdk(payload)

        # HTTP fallback
        if not _HAS_REQUESTS:
            raise AIInterfaceError("Neither OpenAI SDK nor 'requests' is available.")

        if stream:
            return self._stream_http(payload)
        return self._nonstream_http(payload)

    # ---------------------------------
    # Back-compat wrappers (query/ask)
    # ---------------------------------
    def query(
        self,
        user_or_messages: Union[str, List[Dict[str, Any]]],
        system: Optional[str] = None,
        assistant: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Union[str, Generator[str, None, None]]:
        """
        Backward-compatible wrapper around .chat().
        - If a string is passed, it’s treated as the user prompt with optional system/assistant.
        - If a messages list is passed, it’s used as-is.
        """
        if isinstance(user_or_messages, str):
            messages = make_messages(system, user_or_messages, assistant)
        else:
            messages = user_or_messages
        return self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            extra=extra,
        )

    # Some older code calls .ask(); keep it as an alias.
    def ask(self, *args, **kwargs):
        return self.query(*args, **kwargs)

    # -------------
    # SDK paths
    # -------------

    def _nonstream_sdk(self, payload: Dict[str, Any]) -> str:
        resp = self._client.chat.completions.create(timeout=self.request_timeout, **payload)  # type: ignore
        # New SDK shape: resp.choices[0].message.content
        try:
            return resp.choices[0].message.content or ""
        except Exception:
            # Fall back to printing the whole response for debugging
            return json.dumps(resp.to_dict_recursive() if hasattr(resp, "to_dict_recursive") else resp, indent=2)

    def _stream_sdk(self, payload: Dict[str, Any]) -> Generator[str, None, None]:
        stream_resp = self._client.chat.completions.create(stream=True, timeout=self.request_timeout, **payload)  # type: ignore
        for event in stream_resp:
            try:
                delta = event.choices[0].delta.content or ""
            except Exception:
                delta = ""
            if delta:
                yield delta

    # -------------
    # HTTP fallback paths
    # -------------

    def _headers(self) -> Dict[str, str]:
        # OpenAI-compatible = Bearer
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self) -> str:
        # Ensure /v1, then append /chat/completions
        base = _ensure_v1(self.base_url)
        return f"{base}/chat/completions"

    def _nonstream_http(self, payload: Dict[str, Any]) -> str:
        sess = requests.Session()
        # hardening: ignore proxy env and system config
        sess.trust_env = False
        sess.proxies = {}  # type: ignore

        url = self._endpoint()
        r = sess.post(url, headers=self._headers(), json=payload, timeout=self.request_timeout)
        if r.status_code >= 400:
            raise AIInterfaceError(self._format_http_error(r))
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except Exception:
            return json.dumps(data, indent=2)

    def _stream_http(self, payload: Dict[str, Any]) -> Generator[str, None, None]:
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {}  # type: ignore

        url = self._endpoint()
        # OpenAI-compatible streaming: stream=True returns SSE/line-delimited chunks
        with sess.post(url, headers=self._headers(), json={**payload, "stream": True},
                       timeout=self.request_timeout, stream=True) as r:
            if r.status_code >= 400:
                raise AIInterfaceError(self._format_http_error(r))
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data:"):
                    datum = line[len("data:"):].strip()
                    if datum == "[DONE]":
                        break
                    try:
                        obj = json.loads(datum)
                        delta = obj["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        # pass malformed lines
                        continue

    @staticmethod
    def _format_http_error(r: "requests.Response") -> str:
        detail = ""
        try:
            detail = json.dumps(r.json(), indent=2)
        except Exception:
            detail = r.text
        return f"HTTP {r.status_code} calling {r.request.method} {r.url}\n{detail}"


# ---------------------------
# Convenience helpers
# ---------------------------

def make_messages(
    system: Optional[str],
    user: str,
    assistant: Optional[str] = None
) -> List[Dict[str, str]]:
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    if assistant:
        msgs.append({"role": "assistant", "content": assistant})
    msgs.append({"role": "user", "content": user})
    return msgs


# ---------------------------
# CLI for quick testing
# ---------------------------

def _cli() -> None:
    p = argparse.ArgumentParser(description="Quick test for ai_interface.py")
    p.add_argument("--provider", default="baseten", help="Provider key (default: baseten)")
    p.add_argument("--model", default=None, help="Model override")
    p.add_argument("--api-key", default=None, help="API key override")
    p.add_argument("--base-url", default=None, help="Base URL override (will normalize to /v1)")
    p.add_argument("--timeout", type=int, default=None, help="Request timeout (seconds)")
    p.add_argument("--system", default=None, help="System prompt")
    p.add_argument("--user", required=True, help="User prompt")
    p.add_argument("--assistant", default=None, help="Optional assistant priming message")
    p.add_argument("--stream", action="store_true", help="Stream output")
    args = p.parse_args()

    ai = AIInterface(
        provider_key=args.provider,
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        request_timeout=args.timeout,
    )

    messages = make_messages(args.system, args.user, args.assistant)

    if args.stream:
        for chunk in ai.chat(messages, stream=True):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        print()  # newline
    else:
        out = ai.chat(messages, stream=False)
        print(out)


if __name__ == "__main__":
    _cli()

