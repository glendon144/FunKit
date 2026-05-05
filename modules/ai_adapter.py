# modules/ai_adapter.py
import os
import logging
import inspect
from typing import Iterable, Optional, Dict, Any, Callable, List

from modules.pikit_port.ai_interface import AIInterface as PiKitAI
from modules.provider_registry import registry

log = logging.getLogger(__name__)

PROVIDER_ALIASES = {
    "openai": "openai",
    "mistral": "mistral",
    "baseten": "baseten",
    "deepseek": "deepseek",
    "local": "local",
    "local_llama": "local_llama",
    "llamacpp": "llamacpp",
}

ASK_CANDIDATES = [
    "ask",
    "complete",
    "completion",
    "chat",
    "generate",
    "invoke",
    "run",
    "call",
    "create",
    "create_completion",
    "create_chat_completion",
]
STREAM_CANDIDATES = [
    "stream",
    "stream_complete",
    "streaming",
    "stream_chat",
    "iter_stream",
    "sse_stream",
]


def _signature_params(fn: Callable) -> List[str]:
    try:
        return list(inspect.signature(fn).parameters.keys())
    except Exception:
        return []


def _filter_kwargs_for_fn(fn: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    params = set(_signature_params(fn))
    return {k: v for k, v in kwargs.items() if k in params}


def _resolve_method(obj: Any, candidates) -> Optional[Callable]:
    for name in candidates:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn
    return None


def _mk_messages(prompt: str) -> List[Dict[str, str]]:
    return [{"role": "user", "content": prompt}]


def _remap_model_key(fn: Callable, model_value: Optional[str]) -> Dict[str, Any]:
    if model_value is None:
        return {}
    params = set(_signature_params(fn))
    if "model" in params:
        return {"model": model_value}
    if "model_name" in params:
        return {"model_name": model_value}
    return {}


def _mask_key(key: str) -> str:
    if not key:
        return "(missing)"
    if len(key) <= 10:
        return key[:2] + "..."
    return key[:6] + "..." + key[-4:]


class AIInterface:
    def __init__(
        self,
        provider: Optional[str] = None,
        default_model: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_s: int = 120,
    ):
        selected_key = (
            provider or os.getenv("FUNKIT_AI_PROVIDER") or registry.read_selected()
        )
        self._extra_headers = extra_headers or {}
        self._timeout_s = timeout_s
        self._client = None
        self._ask_fn = None
        self._stream_fn = None
        self._provider = ""
        self._default_model = None
        self._cfg = None

        self.set_provider(selected_key, default_model)

    def _build_client(self, cfg, model_to_use: str):
        key_val = os.getenv(cfg.env_key, "") if cfg.env_key else ""
        base_url = cfg.endpoint
        timeout = (
            cfg.extras.get("timeout", self._timeout_s)
            if isinstance(cfg.extras, dict)
            else self._timeout_s
        )

        print(
            f"[AI DEBUG] build_client: provider={cfg.key} "
            f"endpoint={base_url} model={model_to_use} "
            f"env_key={cfg.env_key} key_present={bool(key_val)}"
        )

        self._client = PiKitAI(
            api_key=key_val or None,
            base_url=base_url,
            model=model_to_use,
            timeout=timeout,
        )
        self._ask_fn = _resolve_method(self._client, ASK_CANDIDATES)
        self._stream_fn = _resolve_method(self._client, STREAM_CANDIDATES)

    def ask(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        if not self._ask_fn:
            exported = [n for n in dir(self._client) if not n.startswith("_")]
            raise AttributeError(
                f"Underlying PiKit AIInterface has no ask-like method; tried {ASK_CANDIDATES}. "
                f"Exports: {exported}"
            )

        effective_model = model or self._default_model
        cfg = self._cfg
        key_val = os.getenv(cfg.env_key, "") if (cfg and cfg.env_key) else ""

        print(
            f"[AI DEBUG] ask: provider={self._provider} "
            f"endpoint={cfg.endpoint if cfg else None} model={effective_model} "
            f"env_key={cfg.env_key if cfg else None} key_present={bool(key_val)}" 
        )

        fn = self._ask_fn
        params = set(_signature_params(fn))
        call_kwargs: Dict[str, Any] = {}
        call_kwargs.update(_remap_model_key(fn, effective_model))

        if "messages" in params:
            call_kwargs["messages"] = _mk_messages(prompt)
        elif "prompt" in params:
            call_kwargs["prompt"] = prompt
        elif "input" in params:
            call_kwargs["input"] = prompt
        else:
            call_kwargs["messages"] = _mk_messages(prompt)

        overrides = kwargs.pop("overrides", None)
        if isinstance(overrides, dict):
            kwargs.update(overrides)

        call_kwargs.update(_filter_kwargs_for_fn(fn, kwargs))
        return fn(**call_kwargs)

    def stream(
        self, prompt: str, model: Optional[str] = None, **kwargs
    ) -> Iterable[str]:
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

            overrides = kwargs.pop("overrides", None)
            if isinstance(overrides, dict):
                kwargs.update(overrides)

            call_kwargs.update(_filter_kwargs_for_fn(fn, kwargs))
            yield from fn(**call_kwargs)
            return

        yield self.ask(prompt=prompt, model=model, **kwargs)

    def query(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def complete(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def completion(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.ask(*args, **kwargs)

    def chat(self, messages=None, prompt=None, model=None, **kwargs):
        if prompt is None and messages:
            try:
                prompt = next(
                    (
                        m.get("content", "")
                        for m in reversed(messages)
                        if m.get("role") == "user"
                    ),
                    "",
                )
            except Exception:
                prompt = ""
        return self.ask(prompt or "", model=model, **kwargs)

    def set_provider(self, provider: str, default_model: Optional[str] = None) -> None:
        cfg = registry.get(provider)
        prov = PROVIDER_ALIASES.get(cfg.key.lower(), cfg.key.lower())
        model_to_use = default_model or cfg.model

        self._cfg = cfg
        self._provider = prov
        self._default_model = model_to_use

        self._build_client(cfg, model_to_use)

        print(
            f"[AI DEBUG] set_provider: provider={cfg.key} "
            f"endpoint={cfg.endpoint} model={model_to_use} "
            f"env_key={cfg.env_key} key_present={bool(os.getenv(cfg.env_key, '') if cfg.env_key else '')}"
        )

    def get_provider(self) -> str:
        return self._provider
