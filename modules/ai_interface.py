# ai_interface.py
# Providers: Local Mistral (llama.cpp), OpenAI, Baseten
# Defaults to local Mistral on http://127.0.0.1:8080/v1
# Streaming with optional live display:
#   - Console: export AI_STREAM_STDOUT=1
#   - Callback: ai.query(..., on_token=callable)
# Always returns the full final string (even when streaming).

from __future__ import annotations

import os
import re
import json
from typing import Dict, List, Optional, Any, Tuple, Union, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ----------------------- helpers -----------------------

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v is not None and str(v).strip() != "" else default


def _ensure_v1(base: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/v1") else base + "/v1"


def _new_session(total_retries: int = 3, backoff: float = 0.25) -> requests.Session:
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST", "HEAD"]),
        raise_on_status=False,
    )
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.trust_env = False  # avoid surprise proxies
    s.proxies = {}
    return s


def _resolve_provider_name(name: Optional[str]) -> str:
    """Map common labels/typos to canonical provider ids."""
    if not name:
        return "mistral"  # default to local llama.cpp
    n = name.strip().lower()
    n_compact = re.sub(r"[^a-z0-9]+", "", n)

    # mistral / local llama.cpp
    if any(k in n for k in ("mistral", "llama", "local")) or n_compact in {
        "mistral", "llamacpp", "localllm", "mistralloca", "mistrallocal"
    }:
        return "mistral"

    # baseten (incl. "base10" typo)
    if "baseten" in n or "base10" in n or n_compact in {"baseten", "base10", "basetn"}:
        return "baseten"

    # openai
    if "openai" in n or "gpt" in n or n_compact in {"openai", "oai", "chatgpt"}:
        return "openai"

    if n in {"mistral", "baseten", "openai"}:
        return n
    return "mistral"


def _normalize_messages(
    messages: Union[str, Dict[str, Any], Tuple[str, str], List[Any]]
) -> List[Dict[str, str]]:
    """
    Accept flexible inputs and return a proper OpenAI-style messages array.
    """
    if isinstance(messages, dict) and "messages" in messages:
        messages = messages["messages"]

    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]

    if isinstance(messages, dict):
        role = str(messages.get("role", "user"))
        content = messages.get("content", "")
        return [{"role": role, "content": str(content)}]

    if isinstance(messages, tuple) and len(messages) == 2:
        role, content = messages
        return [{"role": str(role), "content": str(content)}]

    if isinstance(messages, list):
        out: List[Dict[str, str]] = []
        for item in messages:
            if isinstance(item, str):
                out.append({"role": "user", "content": item})
            elif isinstance(item, tuple) and len(item) == 2:
                r, c = item
                out.append({"role": str(r), "content": str(c)})
            elif isinstance(item, dict):
                r = str(item.get("role", "user"))
                c = item.get("content", "")
                out.append({"role": r, "content": str(c)})
            else:
                out.append({"role": "user", "content": str(item)})
        if not out:
            raise ValueError("Empty messages list after normalization.")
        return out

    return [{"role": "user", "content": str(messages)}]


def _parse_timeout_env(prefix: str, default: Union[int, float, Tuple[float, float]]) -> Union[float, Tuple[float, float]]:
    """
    Support:
      PREFIX_TIMEOUT="60"          -> 60.0 (single)
      PREFIX_TIMEOUT="5,300"       -> (5.0, 300.0) (connect, read)
      PREFIX_CONNECT_TIMEOUT=5 and PREFIX_READ_TIMEOUT=300 -> (5.0, 300.0)
    """
    conn = _env(f"{prefix}_CONNECT_TIMEOUT", None)
    read = _env(f"{prefix}_READ_TIMEOUT", None)
    if conn and read:
        return (float(conn), float(read))

    raw = _env(f"{prefix}_TIMEOUT", None)
    if raw and "," in raw:
        a, b = raw.split(",", 1)
        return (float(a.strip()), float(b.strip()))
    if raw:
        return float(raw)

    # default fallback
    if isinstance(default, tuple):
        return (float(default[0]), float(default[1]))
    return float(default)


# ----------------------- provider config -----------------------

class _ProviderConfig:
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key_env: Optional[str] = None,
        auth_scheme: str = "Bearer",
        timeout: Union[int, float, Tuple[float, float]] = 60,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.base_url = _ensure_v1(base_url)
        self.model = model
        self.api_key_env = api_key_env
        self.auth_scheme = auth_scheme
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key_env:
            key = _env(self.api_key_env, None)
            if key:
                if self.auth_scheme.lower() == "api-key":
                    h["Authorization"] = f"Api-Key {key}"
                else:
                    h["Authorization"] = f"Bearer {key}"
        h.update(self.extra_headers)
        return h

    def chat_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def models_url(self) -> str:
        return self.base_url.rstrip("/") + "/models"


# ----------------------- main class -----------------------

class AIInterface:
    """
    Example:
        ai = AIInterface()  # defaults to local mistral (llama.cpp)
        out = ai.query("Say hi in one short sentence.")   # string OK

    Switch at runtime:
        ai.set_provider("mistral" | "baseten" | "openai")

    Env knobs:
        # Local mistral (llama.cpp)
        MISTRAL_BASE=http://127.0.0.1:8080/v1
        MISTRAL_MODEL=local-mistral
        # Timeouts (any of these):
        MISTRAL_TIMEOUT=60
        MISTRAL_TIMEOUT="5,300"              # connect=5s, read=300s
        MISTRAL_CONNECT_TIMEOUT=5
        MISTRAL_READ_TIMEOUT=300

        # OpenAI
        OPENAI_API_KEY=sk-...
        OPENAI_BASE=https://api.openai.com/v1
        OPENAI_MODEL=gpt-4o-mini
        OPENAI_TIMEOUT=60

        # Baseten
        BASETEN_API_KEY=bt-...
        BASETEN_URL=https://YOUR-MODEL.basen.run/v1
        BASETEN_MODEL=baseten
        BASETEN_AUTH_SCHEME=Api-Key   # or Bearer
        BASETEN_TIMEOUT=60

        # Desired default provider
        AI_PROVIDER=mistral|baseten|openai|base10|local|llama...

        # Console streaming
        AI_STREAM_STDOUT=1
    """

    def __init__(self, provider: Optional[str] = None):
        self.session = _new_session()
        self.cfgs: Dict[str, _ProviderConfig] = {
            "mistral": _ProviderConfig(
                name="mistral",
                base_url=_env("MISTRAL_BASE", "http://127.0.0.1:8080/v1"),
                model=_env("MISTRAL_MODEL", "local-mistral"),
                api_key_env=None,  # llama.cpp typically needs no key
                auth_scheme="none",
                timeout=_parse_timeout_env("MISTRAL", (5.0, 300.0)),  # sensible default tuple
            ),
            "openai": _ProviderConfig(
                name="openai",
                base_url=_env("OPENAI_BASE", "https://api.openai.com/v1"),
                model=_env("OPENAI_MODEL", "gpt-4o-mini"),
                api_key_env="OPENAI_API_KEY",
                auth_scheme="Bearer",
                timeout=float(_env("OPENAI_TIMEOUT", "60")),
            ),
            "baseten": _ProviderConfig(
                name="baseten",
                base_url=_env("BASETEN_URL", ""),
                model=_env("BASETEN_MODEL", "baseten"),
                api_key_env="BASETEN_API_KEY",
                auth_scheme=_env("BASETEN_AUTH_SCHEME", "Api-Key"),
                timeout=float(_env("BASETEN_TIMEOUT", "60")),
            ),
        }

        requested = provider or _env("AI_PROVIDER", None)
        self.provider = _resolve_provider_name(requested)

        cfg = self.cfgs[self.provider]
        print(f"[ai_interface] Provider='{self.provider}' → base='{cfg.base_url}' model='{cfg.model}'")

        if self.provider == "baseten" and not cfg.base_url:
            print("[ai_interface] WARNING: BASETEN_URL is not set. Set it or switch provider to 'mistral'/'openai'.")

        self._stream_stdout = _env("AI_STREAM_STDOUT", "0") in {"1", "true", "yes", "on"}

    # -------- API --------

    def set_provider(self, provider: str) -> None:
        prov = _resolve_provider_name(provider)
        if prov not in self.cfgs:
            raise ValueError(f"Unknown provider '{provider}' (canonical='{prov}'). Options: {list(self.cfgs.keys())}")
        self.provider = prov
        cfg = self.cfgs[self.provider]
        print(f"[ai_interface] Switched to '{self.provider}' (base={cfg.base_url}, model={cfg.model})")

    def _post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: Union[float, Tuple[float, float]], stream: bool):
        return self.session.post(url, headers=headers, data=json.dumps(payload), timeout=timeout, stream=stream)

    def _consume_stream(self, resp: requests.Response, on_token: Optional[Callable[[str], None]]) -> str:
        """
        Parse OpenAI-style SSE: lines like 'data: {...}' ending with 'data: [DONE]'.
        Accumulate delta.content pieces. If AI_STREAM_STDOUT=1 or on_token is provided,
        emit tokens live.
        """
        out_parts: List[str] = []
        for raw in resp.iter_lines(decode_unicode=True, chunk_size=8192):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                jd = json.loads(data_str)
                delta = jd["choices"][0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    out_parts.append(piece)
                    if on_token:
                        try:
                            on_token(piece)
                        except Exception:
                            pass
                    if self._stream_stdout:
                        print(piece, end="", flush=True)
            except Exception:
                # Be forgiving of non-standard chunks
                try:
                    jd = json.loads(data_str)
                    msg = jd["choices"][0]["message"]["content"]
                    if isinstance(msg, str):
                        out_parts.append(msg)
                        if on_token:
                            try:
                                on_token(msg)
                            except Exception:
                                pass
                        if self._stream_stdout:
                            print(msg, end="", flush=True)
                except Exception:
                    pass
        if self._stream_stdout:
            print("")  # newline after stream
        return "".join(out_parts).strip()

    def query(
        self,
        messages: Union[str, Dict[str, Any], Tuple[str, str], List[Any]],
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: Optional[bool] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        prov = _resolve_provider_name(provider) if provider else self.provider
        if prov not in self.cfgs:
            raise ValueError(f"Unknown provider '{prov}'. Options: {list(self.cfgs.keys())}")

        cfg = self.cfgs[prov]
        if prov == "baseten" and not cfg.base_url:
            raise RuntimeError(
                "[baseten] BASETEN_URL not set. Export BASETEN_URL=https://YOUR-MODEL.basen.run/v1 "
                "or switch provider to 'mistral' or 'openai'."
            )

        url = cfg.chat_url()
        headers = cfg.headers()

        # Default to streaming for mistral (llama.cpp) to avoid read timeouts
        use_stream = bool(stream) if stream is not None else (prov == "mistral")

        # Normalize any input into a valid messages array
        norm_messages = _normalize_messages(messages)

        payload: Dict[str, Any] = {
            "model": cfg.model,
            "messages": norm_messages,
            "temperature": float(temperature),
            "stream": use_stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if extra_payload:
            payload.update(extra_payload)

        tmo = timeout if timeout is not None else cfg.timeout

        try:
            r = self._post(url, headers, payload, tmo, stream=use_stream)
        except requests.RequestException as e:
            raise RuntimeError(f"[{prov}] Request error: {e}") from e

        if not (200 <= r.status_code < 300):
            body = r.text or ""
            snippet = (body[:500] + "…") if len(body) > 500 else body
            raise RuntimeError(f"[{prov}] HTTP {r.status_code} at {url} — {snippet}")

        if use_stream:
            return self._consume_stream(r, on_token=on_token)

        # Non-stream parse
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError(f"[{prov}] Invalid JSON: {(r.text or '')[:300]}") from e

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"[{prov}] Missing choices/message.content in response: {json.dumps(data)[:400]}") from e

        # If non-stream and user provided on_token, emit once at end (optional)
        if on_token and isinstance(content, str) and content:
            try:
                on_token(content)
            except Exception:
                pass

        return content.strip() if isinstance(content, str) else str(content).strip()

    def health(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Try GET /v1/models (works on OpenAI-compatible servers like llama.cpp)."""
        prov = _resolve_provider_name(provider) if provider else self.provider
        cfg = self.cfgs[prov]
        url = cfg.models_url()
        try:
            r = self.session.get(url, headers=cfg.headers(), timeout=cfg.timeout if isinstance(cfg.timeout, (int, float)) else 15.0)
            ok = 200 <= r.status_code < 300
            return {"ok": ok, "status": r.status_code, "url": url, "body": (r.text[:200] if not ok else "")}
        except requests.RequestException as e:
            return {"ok": False, "error": str(e), "url": url}


# ----------------------- CLI smoke test -----------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ai_interface smoke test")
    p.add_argument("--provider", default=_env("AI_PROVIDER", "mistral"))
    p.add_argument("--prompt", default="Say hi in one short sentence.")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max_tokens", type=int, default=None)
    p.add_argument("--no-stream", action="store_true", help="Force non-streaming request")
    p.add_argument("--timeout", default=None, help='Override timeout, e.g. "5,300" or "120"')
    args = p.parse_args()

    ai = AIInterface(provider=args.provider)

    # Optional: simple console printer (demonstrates on_token)
    def _printer(tok: str):
        print(tok, end="", flush=True)

    # Parse CLI timeout
    tmo = None
    if args.timeout:
        if "," in args.timeout:
            a, b = args.timeout.split(",", 1)
            tmo = (float(a), float(b))
        else:
            tmo = float(args.timeout)

    try:
        text = ai.query(
            args.prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            stream=False if args.no_stream else None,  # default streams on mistral
            timeout=tmo,
            on_token=_printer if _env("AI_STREAM_STDOUT", "0") in {"1", "true", "yes", "on"} else None,
        )
        # Ensure newline when not streaming or when callback wasn’t set
        if _env("AI_STREAM_STDOUT", "0") not in {"1", "true", "yes", "on"}:
            print(text)
        else:
            print()  # newline after streamed printing
    except Exception as e:
        print(f"ERROR: {e}")

