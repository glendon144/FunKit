## v1.2.1 — 2025-08-14

✨ **PiKit / DemoKit — v1.2.1**

🌐 **URL → OPML importer (async, resilient)**
- Background fetch with timeouts, size caps, and content-type checks
- **Quick** (≈12s/≈600KB) and **Full** (≈25s/≈2.5MB) modes
- **Cancelable** “Fetching URLs…” dialog
- HTML → OPML via engine; **text fallback** if HTML parse fails
- All **database writes on the main thread** (no SQLite thread errors)

🗂️ **SAFE Batch OPML**
- Multi-select docs → **Create OPML copies**; originals are untouched
- Optional header-link insertion (toggle in Preferences)

🧩 **OPML rendering & recovery**
- Embedded OPML tree view with caret expand/collapse
- Fallback renderer for “OPML-ish” text
- “Repair current doc → OPML (overwrite)” and **Batch: Repair selected OPML**

🧹 **Formatting fixes**
- Fixed literal `\n` → real newlines in headers
- Title bar normalization (no more accumulating phase tags)

⚙️ **Preferences**
- After Convert: **Open / Link / Open+Link**
- Batch: **prepend header link** (optional)
- Network/URL: **Quick vs Full** mode toggle

🔒 **Stability**
- Validation of OPML before save; trims leading noise
- GUI remains responsive during network operations

Thanks for the great collaboration! 🚀

## ✨ OPML Rendering & TreeView lineage milestone — 2025-08-07

- Automatic OPML detection and rendering in the document pane.
- Integrated OPML parsing directly into _render_document (BOM-safe).
- Fixed geometry manager conflict (grid vs pack) in OPML view.
- Restored toolbar handlers (e.g., _on_delete_clicked, _handle_image).
- TreeView lineage displays correctly from green links.
- OPML tree depth preference persists until changed by user.

Tagging this as the first stable OPML-capable build of PiKit.

