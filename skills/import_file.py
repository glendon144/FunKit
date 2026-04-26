"""
skill_import_file — import a filesystem file into the document store.

Contract
--------
Inputs:
    doc_store   DocumentStore   an open FunKit document store
    path        str | Path      path to the file to import
    title       str | None      document title; defaults to the file stem

Outputs:
    int — the new document ID assigned by the store

Side effects:
    Reads the file at *path* from the filesystem.
    Creates exactly one new row in the document store (SQLite INSERT).

Dependencies:
    modules.document_store.DocumentStore
    pathlib.Path  (stdlib)

Risk level:        LOW
AI Broker approval: NOT REQUIRED

Notes:
    - Text files are stored as UTF-8 strings.
    - Binary files (non-UTF-8) are stored as raw bytes (SQLite BLOB).
    - The caller is responsible for checking that *path* exists before calling.
    - This skill does NOT call AI and does NOT modify any existing documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


def import_file(
    doc_store,
    path: Union[str, Path],
    title: str | None = None,
) -> int:
    """Import the file at *path* into *doc_store* and return the new document ID.

    Raises:
        FileNotFoundError   if *path* does not exist
        PermissionError     if *path* is not readable
        RuntimeError        if the document store INSERT fails
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    doc_title = title or p.stem

    try:
        body: Union[str, bytes] = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        body = p.read_bytes()

    try:
        new_id: int = doc_store.add_document(doc_title, body)
    except Exception as exc:
        raise RuntimeError(f"Document store INSERT failed for {p}: {exc}") from exc

    return new_id


# ---------------------------------------------------------------------------
# CLI smoke-test:  python -m skills.import_file <db_path> <file_path> [title]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m skills.import_file <db_path> <file_path> [title]")
        sys.exit(1)

    db_path = sys.argv[1]
    file_path = sys.argv[2]
    doc_title = sys.argv[3] if len(sys.argv) > 3 else None

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from modules.document_store import DocumentStore  # type: ignore

    store = DocumentStore(db_path)
    new_id = import_file(store, file_path, title=doc_title)
    print(f"Imported '{file_path}' → document ID {new_id}")
