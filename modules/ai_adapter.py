# modules/ai_adapter.py
import os
import logging
import inspect
from typing import Iterable, Optional, Dict, Any, Callable, List

from modules.pikit_port.ai_interface import AIInterface as PiKitAI

log = logging.getLogger(__name__)

PROVIDER_ALIASES = {
    "openai": "openai",
    "mistral": "mistral",
    "baseten": "baseten",
    "local": "local",
    "llamacpp": "llamacpp",
}

# Likely names PiKit might use for non-stream and stream entrypoints
ASK_CANDIDATES = [
    "ask", "complete", "completion", "chat", "generate",
    "invoke", "run", "call", "create", "create_completion", "create_chat_completion",
]
STREAM_CANDIDATES = [
    "stream", "stream_complete", "streaming", "stream_chat",
    "iter_stream", "sse_stream",
]


def _signature_params(fn: Callable) -> List[str]:
    try:
        return list(inspect.signature(fn).parameters.keys())
    except Exception:
        return []


def _filter_kwargs_for_fn(fn: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Pass only kwargs the target function accepts."""
    params = set(_signature_params(fn))
    return {k: v for k, v in kwargs.items() if k in params}


def _filter_kwargs_for_ctor(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Pass only kwargs supported by the class constructor."""
    try:
        sig = inspect.signature(cls.__init__)
        valid = {p.name for p in sig.parameters.values() if p.name != "self"}
        return {k: v for k, v in kwargs.items() if k in valid}
    except Exception:
        return {}


def _resolve_method(obj: Any, candidates) -> Optional[Callable]:
    for name in candidates:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn
    return None


def _mk_messages(prompt: str) -> List[Dict[str, str]]:
    return [{"role": "user", "content": prompt}]


def _remap_model_key(fn: Callable, model_value: Optional[str]) -> Dict[str, Any]:
    """Some clients expect 'model', others 'model_name'."""
    if model_value is None:
        return {}
    params = set(_signature_params(fn))
    if "model" in params:
        return {"model": model_value}
    if "model_name" in params:
        return {"model_name": model_value}
    return {}


class AIInterface:
    """
    FunKit-facing adapter that delegates to PiKit's AI engine while preserving
    FunKit method names/signatures. It auto-detects and adapts arguments.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        default_model: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_s: int = 120,
    ):
        prov = provider or os.getenv("FUNKIT_AI_PROVIDER") or "openai"
        prov = PROVIDER_ALIASES.get(prov.lower(), prov.lower())

        self._provider = prov
        self._default_model = default_model
        self._extra_headers = extra_headers or {}
        self._timeout_s = timeout_s

        ctor_kwargs = {
            "provider": prov,
            "default_model": default_model,
            "timeout": timeout_s,
            "extra_headers": self._extra_headers,
        }
        filtered = _filter_kwargs_for_ctor(PiKitAI, ctor_kwargs)

        try:
            self._client = PiKitAI(**filtered)
        except TypeError:
            self._client = PiKitAI()

        # Resolve callable entrypoints once
        self._ask_fn = _resolve_method(self._client, ASK_CANDIDATES)
        self._stream_fn = _resolve_method(self._client, STREAM_CANDIDATES)

        log.info("AIAdapter initialized (provider=%s, model=%s)", prov, default_model)

    # --- FunKit API ---

    def ask(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        """
        Accepts FunKit's prompt+model and adapts to PiKit's API.
        If the target fn expects `messages`, we build them.
        """
        if not self._ask_fn:
            exported = [n for n in dir(self._client) if not n.startswith("_")]
            raise AttributeError(
                f"Underlying PiKit AIInterface has no ask-like method; tried {ASK_CANDIDATES}. "
                f"Exports: {exported}"
            )

        fn = self._ask_fn
        params = set(_signature_params(fn))

        # Build call kwargs
        call_kwargs: Dict[str, Any] = {}
        # Model key remap
        call_kwargs.update(_remap_model_key(fn, model or self._default_model))

        if "messages" in params:
            call_kwargs["messages"] = _mk_messages(prompt)
        elif "prompt" in params:
            call_kwargs["prompt"] = prompt
        elif "input" in params:
            call_kwargs["input"] = prompt
        else:
            # As a last resort, still try 'messages'
            call_kwargs["messages"] = _mk_messages(prompt)

        # Carry over any extra kwargs the target supports (temperature, max_tokens, etc.)
        call_kwargs.update(_filter_kwargs_for_fn(fn, kwargs))

        return fn(**call_kwargs)

    def stream(self, prompt: str, model: Optional[str] = None, **kwargs) -> Iterable[str]:
        """
        Prefer a true streaming API. If not available, yield once from ask().
        """
        if callable(self._stream_fn):
            fn = self._stream_fn
            params = set(_signature_params(fn))
            call_kwargs: Dict[str, Any] = {}
            call_kwargs.update(_remap_model_key(fn, model or self._default_model))

            if "messages" in params:
                call_kwargs["messages"] = _mk_messages(prompt)
            elif "prompt" in params:
                call_kwargs["prompt"] = prompt
            elif "input" in params:
                call_kwargs["input"] = prompt
            else:
                call_kwargs["messages"] = _mk_messages(prompt)

            call_kwargs.update(_filter_kwargs_for_fn(fn, kwargs))
            yield from fn(**call_kwargs)
            return

        # Fallback: single non-streaming call
        yield self.ask(prompt=prompt, model=model, **kwargs)
        # --- Compat aliases used by older FunKit code paths ---
    def query(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def complete(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def completion(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def chat(self, messages=None, prompt=None, model=None, **kwargs):
        # If a caller passes messages, try to use the underlying chat/complete;
        # otherwise just treat as a normal ask().
        if messages is not None:
            fn = getattr(self, "_ask_fn", None)
            if callable(fn):
                # Prefer message-shaped calls; our ask already adapts keys too.
                try:
                    return self.ask(prompt=prompt or "", model=model, messages=messages, **kwargs)
                except TypeError:
                    pass
        # Fallback: reduce to a single prompt
        if prompt is None and messages:
            try:
                prompt = next((m.get("content","") for m in reversed(messages) if m.get("role")=="user"), "")
            except Exception:
                prompt = ""
        return self.ask(prompt or "", model=model, **kwargs)

    def set_provider(self, provider: str, default_model: Optional[str] = None) -> None:
        prov = PROVIDER_ALIASES.get(provider.lower(), provider.lower())
        setter = getattr(self._client, "set_provider", None)

        if callable(setter):
            try:
                # Try (provider, model) if supported
                sig = inspect.signature(setter)
                if len(sig.parameters) >= 2:
                    setter(prov, default_model or self._default_model)
                else:
                    setter(prov)
            except Exception:
                setter(prov)
        else:
            # Rebuild the client if live switching isn't supported
            ctor_kwargs = {
                "provider": prov,
                "default_model": default_model or self._default_model,
                "timeout": self._timeout_s,
                "extra_headers": self._extra_headers,
            }
            filtered = _filter_kwargs_for_ctor(PiKitAI, ctor_kwargs)
            try:
                self._client = PiKitAI(**filtered)
            except TypeError:
                self._client = PiKitAI()
            # Re-resolve methods after rebuilding
            self._ask_fn = _resolve_method(self._client, ASK_CANDIDATES)
            self._stream_fn = _resolve_method(self._client, STREAM_CANDIDATES)

        self._provider = prov
        if default_model:
            self._default_model = default_model

    def get_provider(self) -> str:
        return self._provider

    def models(self):
        fn = getattr(self._client, "models", None)
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                return []
        return []

    def healthcheck(self) -> Dict[str, Any]:
        fn = getattr(self._client, "healthcheck", None)
        if callable(fn):
            try:
                return fn()
            except Exception as e:
                return {"ok": False, "error": str(e), "provider": self._provider}
        return {"ok": True, "provider": self._provider}

