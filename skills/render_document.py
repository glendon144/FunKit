"""
skill_render_document — return a text rendering of a stored document.

Contract
--------
Inputs:
    doc_store   DocumentStore   an open FunKit document store
    doc_id      int             ID of the document to render

Outputs:
    str — UTF-8 text content of the document, or an error sentinel string
          starting with "[ERROR]" if the document is not found.

Side effects:
    None — pure read.

Dependencies:
    modules.document_store.DocumentStore
    modules.renderer.render_binary_as_text  (optional; falls back gracefully)

Risk level:        LOW
AI Broker approval: NOT REQUIRED
"""

from __future__ import annotations

import os
from typing import Any, Tuple


# ---------------------------------------------------------------------------
# Optional renderer — graceful fallback if not installed
# ---------------------------------------------------------------------------

try:
    from modules.renderer import render_binary_as_text  # type: ignore
except Exception:
    try:
        from modules.hypertext_parser import render_binary_as_text  # type: ignore
    except Exception:
        def render_binary_as_text(data_or_path: Any, title: str = "Document") -> str:
            if isinstance(data_or_path, (bytes, bytearray)):
                return data_or_path.decode("utf-8", errors="replace")
            if isinstance(data_or_path, str) and os.path.exists(data_or_path):
                with open(data_or_path, "rb") as f:
                    return f.read().decode("utf-8", errors="replace")
            return str(data_or_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_row(row: Any) -> Tuple[Any, str, Any]:
    """Normalize a document row to (id, title, body)."""
    try:
        if hasattr(row, "keys"):
            keys = set(row.keys())
            return (
                row["id"] if "id" in keys else None,
                row["title"] if "title" in keys else "Document",
                row["body"] if "body" in keys else "",
            )
    except Exception:
        pass
    if isinstance(row, dict):
        return row.get("id"), (row.get("title") or "Document"), row.get("body")
    try:
        if not isinstance(row, (str, bytes, bytearray)) and hasattr(row, "__getitem__"):
            return (
                row[0] if len(row) > 0 else None,
                row[1] if len(row) > 1 else "Document",
                row[2] if len(row) > 2 else "",
            )
    except Exception:
        pass
    return None, "Document", row


# ---------------------------------------------------------------------------
# Public skill entry point
# ---------------------------------------------------------------------------

def render_document(doc_store, doc_id: int) -> str:
    """Return the text content of *doc_id* from *doc_store*.

    Returns a string starting with "[ERROR]" if the document cannot be found
    or the store raises an exception — never raises itself.
    """
    try:
        row = doc_store.get_document(doc_id)
    except Exception as exc:
        return f"[ERROR] Could not retrieve document {doc_id}: {exc}"

    if not row:
        return f"[ERROR] Document {doc_id} not found."

    _id, title, body = _normalize_row(row)

    # If body is a filesystem path that exists, delegate to renderer
    if isinstance(body, str) and os.path.exists(body):
        try:
            return render_binary_as_text(body, title)
        except Exception:
            pass

    # Binary body
    if isinstance(body, (bytes, bytearray)):
        return render_binary_as_text(body, title)

    return str(body or "")


# ---------------------------------------------------------------------------
# CLI smoke-test:  python -m skills.render_document <db_path> <doc_id>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python -m skills.render_document <db_path> <doc_id>")
        sys.exit(1)

    db_path, raw_id = sys.argv[1], sys.argv[2]

    try:
        doc_id = int(raw_id)
    except ValueError:
        print(f"[ERROR] doc_id must be an integer, got: {raw_id!r}")
        sys.exit(1)

    # Minimal bootstrap — works without the full FunKit GUI stack
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from modules.document_store import DocumentStore  # type: ignore

    store = DocumentStore(db_path)
    result = render_document(store, doc_id)
    print(result)
