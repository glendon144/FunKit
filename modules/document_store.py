import sqlite3
from modules.db_migrations import ensure_ai_memory_table

class DocumentStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_table()
        # Ensure ai_memory exists on startup
        ensure_ai_memory_table(self.conn)  
    def get_connection(self):
        return self.conn    # Return the actual connection object

    def create_table(self):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, title TEXT, body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    # Add this method here clearly:
    def add_document(self, title, body):
        cur = self.conn.execute(
            "INSERT INTO documents (title, body) VALUES (?, ?)", 
            (title, body)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_document(self, doc_id: int, new_body: str):
        """
        Replace the body of an existing document.
        """
        self.conn.execute(
        "UPDATE documents SET body = ? WHERE id = ?",
        (new_body, doc_id)
    )
        self.conn.commit()

    def append_to_document(self, doc_id: int, extra_text: str):
        """
        # Append text to the end of a document body.
        """
        row = self.get_document(doc_id)
        if not row:
            raise ValueError(f"No document with id {doc_id}")

        current_body = row["body"] if isinstance(row, dict) else row[2]
        if current_body is None:
            current_body = ""

        new_body = current_body + "\n" + extra_text
        self.update_document(doc_id, new_body)

    def get_document_index(self):
        """
        Return[{'id': .., 'title': .., 'description': ..}, ...] -
        'description' is a 60-char preview for text docs,
        or "[12345 bytes]" for binary (images, PDFs, ...).
        """
        cur = self.conn.execute(
            "SELECT id, title, body FROM documents ORDER BY id DESC"
        )
        result = []
        for row in cur.fetchall():
            body = row["body"] or b""
            if isinstance(body , bytes):
                # binary file - show size placeholder
                desc = f"[{len(body)} bytes]"
            else:
                # text - first 60 chars, single-line
                desc = body[:60].replace("\n", " ").replace("\r", " ")
            result.append({"id": row["id"], "title": row["title"], "description": desc})
        return result

    def get_document(self, doc_id):
        cur = self.conn.execute("SELECT id, title, body FROM documents WHERE id=?", (doc_id,))
        return cur.fetchone()

    # ... (add your other methods as needed)
    def delete_document(self, doc_id: int):
        """Permanently delete a document and commit changes."""
        self.conn.execute(
            "DELETE FROM documents WHERE id = ?",
            (doc_id,)
        )
        self.conn.commit()
