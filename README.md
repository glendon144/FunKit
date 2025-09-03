# FunKit

A minimal Python toolkit for running ASK/QUERY calls against OpenAI‑compatible endpoints (e.g., **Baseten**).  
It ships with a normalized `AIInterface` that:

- Uses the official **OpenAI SDK** with a custom `base_url`
- Sends `Authorization: Bearer <key>` (what Baseten’s OpenAI‑compatible APIs expect)
- Normalizes to `/v1/chat/completions`
- Supports **streaming** & **non‑streaming**
- Provides back‑compat wrappers: `.query(...)` and `.ask(...)`
- Falls back to **requests** if the SDK isn’t available

---

## Quick start

### Requirements
- Python 3.10+ (3.11+ recommended)
- `pip`

### Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install openai requests
```

### Configure environment
Create a `.env` (or export directly); see `.env.example` in the repo.

```
BASETEN_API_KEY=                         # never commit this
BASETEN_BASE_URL=https://inference.baseten.co/v1
```

If not using dotenv:
```bash
export BASETEN_API_KEY="sk-..." 
export BASETEN_BASE_URL="https://inference.baseten.co/v1"
```

---

## One‑command smoke tests

**Non‑streaming:**
```bash
python -m modules.ai_interface --user "Say hello in 3 words."
```

**Streaming:**
```bash
python -m modules.ai_interface --stream --user "Stream a short sentence."
```

---

## Use in code

```python
from modules.ai_interface import AIInterface

ai = AIInterface(provider_key="baseten")  # reads env vars
print(ai.query("Give me a haiku about FunKit."))

# Or messages style:
out = ai.chat(
    messages=[
        {"role":"system","content":"You are concise."},
        {"role":"user","content":"Explain FunKit in one sentence."}
    ],
    stream=False
)
print(out)
```

---

## Git hygiene (avoid large‑file & secret push blocks)

Add/keep these in `.gitignore`:
```
dist/
build/
*.db
*.sqlite*
*.tgz
*.tar
*.tar.gz
*.zip
.git_corrupt_*/
__pycache__/
*.pyc
.env
.venv/
```

**Optional pre‑push hook** (blocks DBs and >95MB files). Save as `.git/hooks/pre-push` and `chmod +x`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# Block >95MB files
if git ls-files -s | awk '{print $4}' | xargs -I{} -- du -k "{}" 2>/dev/null  | awk '$1>97280 {print $2}' | grep -q .; then
  echo "ERROR: Files >95MB detected. Use Releases/LFS." >&2; exit 1
fi
# Block databases (common secret containers)
if git ls-files | grep -E '\.sqlite3?$|\.db(-old)?$' >/dev/null; then
  echo "ERROR: Database files are tracked. Remove and .gitignore them." >&2; exit 1
fi
```

---

## Troubleshooting

- **403 / Unauthorized:** Ensure `Authorization: Bearer <key>` is used and `BASETEN_API_KEY` is set. Confirm `BASETEN_BASE_URL` ends with `/v1`.
- **404 / wrong route:** We call `/v1/chat/completions`. If you override `base_url`, keep the `/v1` suffix.
- **`AttributeError: 'AIInterface' object has no attribute 'query'`:** Use the FunKit `AIInterface` (it includes `query()` and `ask()`).
- **GitHub push blocked (large files / secrets):** Keep `dist/`, `build/`, `*.db`, and archives (`*.zip|*.tar|*.tgz`) out of git. Use Releases or LFS for binaries. Rotate any credentials if they were ever committed.

---

## License
TBD
