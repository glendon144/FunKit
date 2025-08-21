import os
from pathlib import Path
from typing import Any, Tuple

from modules.logger import Logger
from modules.document_store import DocumentStore
from modules.directory_import import import_text_files_from_directory

# Try both possible locations for render_binary_as_text
try:
    from modules.renderer import render_binary_as_text  # type: ignore
except Exception:  # pragma: no cover
    try:
        from modules.hypertext_parser import render_binary_as_text  # type: ignore
    except Exception:  # pragma: no cover
        def render_binary_as_text(data_or_path: Any, title: str = "Document") -> str:
            """Fallback: best-effort text from bytes or path."""
            try:
                if isinstance(data_or_path, (bytes, bytearray)):
                    return data_or_path.decode("utf-8", errors="replace")
                if isinstance(data_or_path, str) and os.path.exists(data_or_path):
                    with open(data_or_path, "rb") as f:
                        raw = f.read()
                    return raw.decode("utf-8", errors="replace")
            except Exception:
                pass
            return str(data_or_path)


def _normalize_row(row: Any) -> Tuple[Any, str, Any]:
    """Normalize a document row to (id, title, body). Supports sqlite3.Row, dict, tuple/list."""
    # Mapping-like (e.g., sqlite3.Row supports .keys())
    try:
        if hasattr(row, "keys"):
            keys = set(row.keys())
            did = row["id"] if "id" in keys else None
            title = row["title"] if "title" in keys else "Document"
            body = row["body"] if "body" in keys else ""
            return did, title or "Document", body
    except Exception:
        pass

    # Dict
    if isinstance(row, dict):
        return row.get("id"), (row.get("title") or "Document"), row.get("body")

    # Sequence (tuple/list/sqlite3.Row sequence access)
    try:
        if not isinstance(row, (str, bytes, bytearray)) and hasattr(row, "__getitem__"):
            did = row[0] if len(row) > 0 else None
            title = row[1] if len(row) > 1 else "Document"
            body = row[2] if len(row) > 2 else ""
            return did, (title or "Document"), body
    except Exception:
        pass

    # Fallback: treat row itself as body
    return None, "Document", row


class CommandProcessor:
    def __init__(self, store: DocumentStore, ai_interface, logger: Logger | None = None):
        self.doc_store = store
        self.ai = ai_interface
        self.logger = logger if logger else Logger()

    def ask_question(self, prompt: str) -> str | None:
        try:
            self.logger.info(f"Sending standalone prompt to AI: {prompt}")
            response = self.ai.query(prompt)
            self.logger.info("AI response received successfully")
            return response
        except Exception as e:
            self.logger.error(f"AI query failed: {e}")
            return None

    def query_ai(
        self,
        selected_text: str,
        current_doc_id: int,
        on_success,
        on_link_created,
        prefix: str | None = None,
        sel_start: int | None = None,
        sel_end: int | None = None,
    ) -> None:
        """
        Send the selection to AI, create a new doc with the response, optionally embed a green link
        into the original document when the body is text. Never mutates binary bodies.
        """
        # Build prompt
        prompt = f"{prefix} {selected_text}" if prefix else f"Please expand on this: {selected_text}"
        self.logger.info(f"Sending prompt: {prompt}")

        # Call AI
        try:
            reply = self.ai.query(prompt)
        except Exception as e:
            self.logger.error(f"AI query failed: {e}")
            return
        self.logger.info("AI query successful")

        # Create the new AI doc
        new_doc_id = self.doc_store.add_document("AI Response", reply)
        self.logger.info(f"Created new document {new_doc_id}")

        # Try to fetch and update original doc (embed a green link), but only if it's text
        try:
            original = self.doc_store.get_document(current_doc_id)
        except Exception as e:
            original = None
            self.logger.error(f"Failed to load original doc {current_doc_id}: {e}")

        if original is not None:
            try:
                _, title, body = _normalize_row(original)
            except Exception:
                title, body = "Document", ""

            # Only attempt string operations if body is a str
            if isinstance(body, str) and selected_text:
                link_md = f"[{selected_text}](doc:{new_doc_id})"
                updated = None

                # If offsets look valid, use them
                if (
                    isinstance(sel_start, int)
                    and isinstance(sel_end, int)
                    and 0 <= sel_start < sel_end <= len(body)
                ):
                    updated = body[:sel_start] + link_md + body[sel_end:]
                    self.logger.info(f"Embedded link at offsets {sel_start}-{sel_end}")
                else:
                    if selected_text in body:
                        updated = body.replace(selected_text, link_md, 1)
                        self.logger.info("Embedded link by substring replace")
                    else:
                        self.logger.info("Selected text not found in body; leaving original unchanged")

                if updated is not None and updated != body:
                    try:
                        self.doc_store.update_document(current_doc_id, updated)
                    except Exception as e:
                        self.logger.error(f"Failed updating original doc {current_doc_id}: {e}")
            else:
                # Non-text bodies (bytes/bytearray/None) are intentionally not mutated
                if isinstance(body, (bytes, bytearray)):
                    self.logger.info("Original doc is binary; skipping in-place link embed to avoid corruption.")
                else:
                    self.logger.info("Original doc body not a string or no selection; skipping link embed.")
        else:
            self.logger.error(f"Original document {current_doc_id} not found")

        # Fire UI callbacks
        try:
            on_link_created(selected_text)
        except Exception as e:
            self.logger.info(f"on_link_created callback failed (non-fatal): {e}")
        try:
            on_success(new_doc_id)
        except Exception as e:
            self.logger.info(f"on_success callback failed (non-fatal): {e}")

    def get_strings_content(self, doc_id: int) -> str:
        """Return a text rendering of the document suitable for display/export."""
        try:
            row = self.doc_store.get_document(doc_id)
        except Exception:
            row = None

        if not row:
            return "[ERROR] Document not found."

        _, title, body = _normalize_row(row)

        # If body looks like a filesystem path and exists, prefer that
        if isinstance(body, str) and os.path.exists(body):
            try:
                return render_binary_as_text(body, title)
            except Exception:
                pass

        # If it's bytes/bytearray, convert via renderer
        if isinstance(body, (bytes, bytearray)):
            return render_binary_as_text(body, title)

        # Else, return text as-is
        return str(body or "")

    def set_api_key(self, api_key: str) -> None:
        try:
            self.ai.set_api_key(api_key)
            self.logger.info("API key successfully set in AI interface")
        except Exception as e:
            self.logger.error(f"Failed to set API key: {e}")

    def get_context_menu_actions(self) -> dict:
        return {
            "Import CSV": self.doc_store.import_csv,
            "Export CSV": self.doc_store.export_csv,
        }

    # -------- External file operations --------

    def import_document_from_path(self, path: str) -> int:
        """Import a text file from *path* and return new document ID."""
        text = Path(path).read_text(encoding="utf-8")
        title = Path(path).stem
        return self.doc_store.add_document(title, text)

    def export_document_to_path(self, doc_id: int, path: str) -> None:
        """Export document *doc_id* to filesystem path."""
        row = self.doc_store.get_document(doc_id)
        if hasattr(row, "keys"):
            body = row.get("body") if row else ""
        elif isinstance(row, dict):
            body = row.get("body")
        else:
            body = row[2] if row and len(row) > 2 else ""
        p = Path(path)
        if isinstance(body, (bytes, bytearray)):
            p.write_bytes(bytes(body))
        else:
            p.write_text(str(body), encoding="utf-8")

    def save_binary_as_text(self, doc_id: int) -> str:
        """Render binary content as text and store back into document."""
        row = self.doc_store.get_document(doc_id)
        if not row:
            return ""
        _, _, body = _normalize_row(row)
        if isinstance(body, (bytes, bytearray)) or ("\x00" in str(body)):
            text = render_binary_as_text(body)
            self.doc_store.update_document(doc_id, text)
            return text
        return str(body)

    def import_opml_from_path(self, path: str) -> int:
        """Import an OPML/XML file from *path* and return new document ID."""
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        title = Path(path).stem
        return self.doc_store.add_document(title, content)

    def import_directory(self, directory: str) -> None:
        """Bulk-import text files from a directory."""
        import_text_files_from_directory(self.doc_store, directory)
