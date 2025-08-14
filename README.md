# PiKit

PiKit is a fast, minimal knowledge workbench for text, HTML, and OPML.  
It stores everything in a lightweight SQLite DB and lets you import, convert, and outline content quickly.

## ✨ Highlights (v1.2.2)

- 🌐 **URL → OPML importer**  
  - Paste one or many URLs (spaces, commas, semicolons, or newlines)  
  - Auto-adds `https://` and strips common brackets like `<…>` or `(…)`  
  - Converts HTML to clean OPML outlines (uses `aopmlengine` if present; else a lightweight fallback)
- 🧰 **OPML menu + hotkeys + toolbar buttons**  
  - `Ctrl+U` — URL → OPML  
  - `Ctrl+Shift+O` / `Ctrl+Alt+O` / `F6` — Convert Selection → OPML  
  - `Shift+F6` — Batch: Convert Selected → OPML  
  - Buttons appear on the main toolbar: **URL → OPML**, **Convert → OPML**, **Batch → OPML**
- 🧵 **Thread-safe DB writes**  
  All SQLite writes happen on the Tk main thread (no cross-thread errors).
- 🧹 **Export / Save-as-Text polish**  
  Safer handling of binary vs. text documents; better default extensions.

---

## 🚀 Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # if present
python3 main.py
Database: storage/documents.db is created automatically.

GUI: Tkinter app with a left sidebar (documents) and a right pane (viewer/editor).

🧭 Daily Flow


Import a URL as OPML
Click OPML → URL → OPML… or press Ctrl+U

Paste one or more URLs separated by spaces, commas, semicolons, or newlines

Examples:

cnn.com bbc.com; lemonde.fr

https://opml.org\nhttps://example.com

PiKit fetches each page, converts HTML→OPML, and adds a new document.



The importer prefers modules/aopmlengine.py if available. Otherwise it uses a lightweight headings→outline converter.


Convert text selection → OPML
Select text in the document pane → OPML → Convert Selection → OPML (or Ctrl+Shift+O / Ctrl+Alt+O / F6).

If no selection is present and the doc is text, PiKit converts the whole document.



Batch convert sidebar selection → OPML
Multi-select documents in the left sidebar (Shift/Ctrl-click), then OPML → Batch: Convert Selected → OPML (or Shift+F6).

Skips binaries and docs already in OPML.



Save binary as text (recover garbled imports)
Open the binary/garbled doc → SAVE AS TEXT button.

Choose a filename; re-import the saved text file if needed.

🖱 Toolbar & Menu


If your gui_tkinter.py exposes the toolbar:

# inside _build_main_pane()
btns = tk.Frame(pane)
btns.grid(row=2, column=0, sticky="we", pady=(6, 0))
self.toolbar = btns  # <— enables plugin buttons
you’ll see 3 buttons: URL → OPML, Convert → OPML, Batch → OPML.

The OPML menu is also added for all users.

🔌 Plugin wiring


Ensure these two lines appear after creating app in main.py:

from modules.opml_extras_plugin_v3 import install_opml_extras_into_app
from modules.save_as_text_plugin_v3 import install_save_as_text_into_app

install_opml_extras_into_app(app)
install_save_as_text_into_app(app)
Remove older duplicates such as opml_extras_plugin (v1/v2) or export_doc_patch.

🛠 Build Binaries


Standard (spec)
pyinstaller pykit.spec
Lean (minimal deps)
pyinstaller pykit_lean.spec
Standalone (onefile)
pyinstaller --onefile --name pikit-standalone main.py
Artifacts appear in dist/.

🧩 Troubleshooting
“URL can’t contain control characters … (found ‘ ’)”

Split multiple URLs with spaces/commas/semicolons/newlines. The importer now handles these; if you still see this, check for accidental line breaks inside a single URL.

Unicode header error ('latin-1' codec…)

We use an ASCII-only User-Agent string for HTTP requests. If you customize headers, keep them ASCII.

sqlite3 cross-thread errors

All DB writes are executed on the Tk main thread via app.after(0, ...). If you add new background tasks, follow the same pattern.

Binary vs. text export

Exporter chooses write_bytes for bytes and write_text for strings. If you change extensions manually, PiKit will still attempt the right behavior.

📜 Changelog (excerpt)


v1.2.2
URL → OPML: flexible multi-URL parsing; auto https://; safe headers

Thread-safe DB writes (UI thread marshaling)

OPML menu + hotkeys; toolbar integration

Export and OPML rendering polish

❤️ Thanks


PiKit is evolving rapidly. Ideas, issues, or PRs are welcome!

