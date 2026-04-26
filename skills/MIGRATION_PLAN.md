# FunKit Command-to-Skill Migration Plan

## Overview

`command_processor.py` bundles 12 distinct operations into a single class that
mixes AI calls, document store mutations, filesystem I/O, and UI callbacks.
This plan decomposes each operation into a discrete, testable skill with a
well-defined contract and a clear AI Broker disposition.

---

## Code Quality Issues Found (fix before migrating)

1. **Broken method extrusion (lines 370–433):** `import_opml_from_string`,
   `import_opml_from_url`, and `crawl_opml_and_import` are defined as
   *module-level* functions with a `self` parameter — they appear to have been
   accidentally un-indented from the class body. They will raise `TypeError` if
   called on an instance.

2. **Duplicate imports (lines 370–371):** `import os` and `import tempfile`
   appear a second time at module scope inside the class block, which is a
   syntax/logic smell.

3. **Orphaned `import_directory` (line 436):** Indented as a class method but
   appears after the module-level function block — its class membership is
   ambiguous depending on the Python parser's whitespace interpretation.

4. **Temp-file leak in `import_opml_from_string`:** The cleanup block is
   commented out with no explanation; temp files accumulate in `storage/`.

---

## Command Inventory & Analysis

### 1. `set_api_key(api_key)`
| Field | Value |
|---|---|
| **Inputs** | `api_key: str` |
| **Outputs** | None |
| **Side effects** | Mutates in-memory AI interface state |
| **Dependencies** | `ai_interface.set_api_key()` |
| **Risk** | LOW — no I/O, no external calls, local state only |
| **AI Broker approval** | NO |
| **Skill name** | `skill_set_api_key` |
| **Notes** | Trivial delegation; may be removed entirely if broker manages keys |

---

### 2. `get_context_menu_actions()`
| Field | Value |
|---|---|
| **Inputs** | None |
| **Outputs** | `dict[str, callable]` |
| **Side effects** | None |
| **Dependencies** | `doc_store.import_csv`, `doc_store.export_csv` |
| **Risk** | LOW — pure factory, returns callables |
| **AI Broker approval** | NO |
| **Skill name** | `skill_context_menu_actions` |
| **Notes** | UI-layer concern; consider removing from business logic entirely |

---

### 3. `ask_question(prompt)` ⭐ Broker-gated
| Field | Value |
|---|---|
| **Inputs** | `prompt: str` |
| **Outputs** | `str \| None` — sanitized AI response |
| **Side effects** | Writes `recent_prompts` + `last_used` to SQLite memory; calls AI provider |
| **Dependencies** | `ai_interface.query()`, `get_memory()`, `set_memory()`, `sanitize_ai_reply()` |
| **Risk** | MEDIUM — incurs API cost; writes to shared memory table |
| **AI Broker approval** | **YES** — LLM call; subject to budget and provider policy |
| **Skill name** | `skill_ask_question` |
| **Notes** | Adaptive token policy (SHORT_MAX/LONG_MAX) should be preserved; memory preamble injection should be optional |

---

### 4. `query_ai(selected_text, current_doc_id, on_success, on_link_created, ...)` ⭐ Broker-gated
| Field | Value |
|---|---|
| **Inputs** | `selected_text: str`, `current_doc_id: int`, `on_success: callable`, `on_link_created: callable`, `prefix: str\|None`, `sel_start: int\|None`, `sel_end: int\|None` |
| **Outputs** | None (results delivered via callbacks) |
| **Side effects** | Creates new document; mutates original document body (green link embed); writes memory breadcrumbs; fires two UI callbacks |
| **Dependencies** | `ai_interface`, `doc_store` (read + write), `get_memory/set_memory`, `sanitize_ai_reply` |
| **Risk** | HIGH — modifies existing documents in place, creates new documents, calls AI, fires UI callbacks |
| **AI Broker approval** | **YES** — LLM call + document store mutation |
| **Skill name** | `skill_query_and_link` |
| **Notes** | The callback coupling to UI is the biggest portability problem; decouple by returning `(new_doc_id, updated_body)` instead |

---

### 5. `import_document_from_path(path)` ✅ Implemented below
| Field | Value |
|---|---|
| **Inputs** | `path: str` — filesystem path to file |
| **Outputs** | `int` — new document ID |
| **Side effects** | Reads filesystem; creates one document row in SQLite store |
| **Dependencies** | `doc_store.add_document()`, `Path`, `render_binary_as_text` (binary fallback) |
| **Risk** | LOW — deterministic, reversible (delete the doc), no AI, no network |
| **AI Broker approval** | NO |
| **Skill name** | `skill_import_file` ← **implemented** |

---

### 6. `export_document_to_path(doc_id, path)`
| Field | Value |
|---|---|
| **Inputs** | `doc_id: int`, `path: str` |
| **Outputs** | None |
| **Side effects** | Writes (potentially overwrites) a file on the filesystem |
| **Dependencies** | `doc_store.get_document()`, `Path` |
| **Risk** | MEDIUM — overwrites files without confirmation; irreversible if path already exists |
| **AI Broker approval** | NO — but should validate path doesn't overwrite existing files without a `force` flag |
| **Skill name** | `skill_export_document` |
| **Notes** | Add `overwrite: bool = False` guard before implementing as skill |

---

### 7. `get_strings_content(doc_id)` ✅ Implemented below
| Field | Value |
|---|---|
| **Inputs** | `doc_id: int` |
| **Outputs** | `str` — text rendering of document |
| **Side effects** | None — pure read |
| **Dependencies** | `doc_store.get_document()`, `render_binary_as_text` |
| **Risk** | LOW — read-only, no AI, no mutations |
| **AI Broker approval** | NO |
| **Skill name** | `skill_render_document` ← **implemented** |

---

### 8. `import_opml_from_path(path)`
| Field | Value |
|---|---|
| **Inputs** | `path: str` |
| **Outputs** | `int` — new document ID |
| **Side effects** | Reads file; creates document in store |
| **Dependencies** | `doc_store.add_document()`, `Path` |
| **Risk** | LOW — same profile as `import_document_from_path` |
| **AI Broker approval** | NO |
| **Skill name** | `skill_import_opml_file` |

---

### 9. `import_opml_from_string(xml_text, source)` ⚠️ Bug
| Field | Value |
|---|---|
| **Inputs** | `xml_text: str`, `source: str` |
| **Outputs** | `int` — new document ID |
| **Side effects** | Writes temp file to `storage/` (never cleaned up — BUG); creates document in store |
| **Dependencies** | `tempfile`, `import_opml_from_path`, `doc_store` |
| **Risk** | LOW-MEDIUM — storage leak from orphaned temp files |
| **AI Broker approval** | NO |
| **Skill name** | `skill_import_opml_string` |
| **Notes** | Fix temp file leak before promoting to skill; use `delete=True` or explicit cleanup in `finally` |

---

### 10. `import_opml_from_url(url, timeout)` ⭐ Broker-gated
| Field | Value |
|---|---|
| **Inputs** | `url: str`, `timeout: int` |
| **Outputs** | `int` — new document ID |
| **Side effects** | Makes outbound HTTP GET; creates document in store |
| **Dependencies** | `requests`, `import_opml_from_string` |
| **Risk** | MEDIUM — external network call; content is untrusted |
| **AI Broker approval** | **YES** — outbound network request; subject to allowed-domains policy |
| **Skill name** | `skill_import_opml_url` |
| **Notes** | Should validate URL scheme (https only) and optionally check against an allowlist |

---

### 11. `crawl_opml_and_import(start, max_depth)` ⭐ Broker-gated
| Field | Value |
|---|---|
| **Inputs** | `start: str` (URL or path), `max_depth: int` |
| **Outputs** | `list[int]` — new document IDs |
| **Side effects** | Makes potentially many outbound HTTP requests; creates many documents |
| **Dependencies** | `opml_crawler_adapter.crawl_opml`, `import_opml_from_string` |
| **Risk** | HIGH — unbounded network fan-out; bulk document creation; can exhaust storage |
| **AI Broker approval** | **YES** — network + bulk store mutation; should require explicit budget and depth cap policy |
| **Skill name** | `skill_crawl_opml` |
| **Notes** | Broker should enforce `max_depth ≤ policy.max_crawl_depth`; add dry-run mode |

---

### 12. `import_directory(directory)`
| Field | Value |
|---|---|
| **Inputs** | `directory: str` |
| **Outputs** | None (documents created as side effect) |
| **Side effects** | Reads all text files in directory tree; creates many documents |
| **Dependencies** | `import_text_files_from_directory`, `doc_store` |
| **Risk** | MEDIUM — bulk operation; no count/size limit |
| **AI Broker approval** | NO — but should add `max_files` guard |
| **Skill name** | `skill_import_directory` |
| **Notes** | Expose count of imported files in return value |

---

## Migration Priority Order

| Priority | Skill | Reason |
|---|---|---|
| 1 | `skill_render_document` | Pure read, zero risk, high utility |
| 2 | `skill_import_file` | Low risk, foundational for other flows |
| 3 | `skill_import_opml_file` | Same profile as #2 |
| 4 | `skill_export_document` | Add overwrite guard first |
| 5 | `skill_import_opml_string` | Fix temp leak first |
| 6 | `skill_import_directory` | Add max_files cap |
| 7 | `skill_ask_question` | Wire to AI Broker |
| 8 | `skill_import_opml_url` | Wire to AI Broker domain policy |
| 9 | `skill_query_and_link` | Decouple from UI callbacks first |
| 10 | `skill_crawl_opml` | Requires Broker depth/budget policy |
