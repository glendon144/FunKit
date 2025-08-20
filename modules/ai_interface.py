import os
import openai
from modules.logger import Logger


class AIInterface:
    KEY_PATH = os.path.expanduser("~/openai.key")

    def __init__(self, logger=None):
        self.logger = logger or Logger()
        self.api_key = None
        if os.path.exists(self.KEY_PATH):
            self.set_api_key(open(self.KEY_PATH).read().strip())

    def set_api_key(self, key: str):
        self.api_key = key.strip()
        openai.api_key = self.api_key
        self.logger.info("OpenAI API key set.")

    def query(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("OpenAI API key not set")
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-5",
                messages=[{"role": "user", "content": prompt}],
                temperature=1,
            )
            reply = resp["choices"][0]["message"]["content"].strip()
            self.logger.info(f"AI reply received ({len(reply)} chars)")
            return reply
        except Exception as exc:
            self.logger.error(f"OpenAI error: {exc}")
            raise
# --- Tri-model interface (Immediate / Long / Synthesis) ---
import threading

class TriAIInterface(AIInterface):
    """Specialized interface that routes prompts to three different models.

    Uses per-model locks to avoid thread-collision on shared resources.
    Models can be overridden with env vars: IMMEDIATE_MODEL, LONG_MODEL, SYNTH_MODEL.
    """
    def __init__(self, logger=None):
        super().__init__(logger=logger)
        self.immediate_model = os.getenv("IMMEDIATE_MODEL", "gpt-4o-mini")
        self.long_model = os.getenv("LONG_MODEL", "gpt-4.1")
        self.synth_model = os.getenv("SYNTH_MODEL", "gpt-5")
        self._locks = {
            "immediate": threading.Lock(),
            "long": threading.Lock(),
            "synth": threading.Lock(),
        }

    def _require_key(self):
        if not self.api_key:
            raise RuntimeError("OpenAI API key not set")
        openai.api_key = self.api_key

    def _chat(self, *, model: str, prompt: str, temperature: float = 1.0) -> str:
        self._require_key()
        try:
            # Some models only accept default temperature, so omit param completely
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            resp = openai.ChatCompletion.create(**kwargs)
            reply = resp["choices"][0]["message"]["content"].strip()
            self.logger.info(f"AI reply received ({len(reply)} chars) from {model}")
            return reply
        except Exception as exc:
            self.logger.error(f"OpenAI error ({model}): {exc}")
            raise

    # Convenience calls
    def query_immediate(self, prompt: str, temperature: float = 1.0) -> str:
        with self._locks["immediate"]:
            return self._chat(model=self.immediate_model, prompt=prompt, temperature=temperature)

    def query_longterm(self, prompt: str, temperature: float = 1.0) -> str:
        with self._locks["long"]:
            return self._chat(model=self.long_model, prompt=prompt, temperature=temperature)

    def query_synthesis(self, prompt: str, temperature: float = 1.0) -> str:
        with self._locks["synth"]:
            return self._chat(model=self.synth_model, prompt=prompt, temperature=temperature)

