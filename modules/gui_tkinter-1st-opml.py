import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from modules.renderer import render_binary_as_text
from PIL import ImageTk, Image
from modules import hypertext_parser, image_generator, document_store
from modules.logger import Logger
from tkinter import filedialog, messagebox
from modules.directory_import import import_text_files_from_directory
from modules.TreeView import open_tree_view
import subprocess
import sys
import json
import re  # for parsing (doc:ID) links

class DemoKitGUI(tk.Tk):
    """DemoKit GUI – ASK / IMAGE / BACK buttons, context menu, image overlay, and history."""

    def _looks_like_image(self, title: str) -> bool:
        return title.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))

    def _show_image_bytes(self, raw: bytes):
        from io import BytesIO
        pil = Image.open(BytesIO(raw))
        w, h = max(100, self.winfo_width()-40), max(100, self.winfo_height()-40)
        pil.thumbnail((w, h))
        self._tk_img = ImageTk.PhotoImage(pil)
        if not hasattr(self, '_img_label'):
            self._img_label = tk.Label(self, bg='black')
        self._img_label.configure(image=self._tk_img)
        if self.text.winfo_manager():
            self.text.pack_forget()
        self._img_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _hide_image(self):
        if hasattr(self, '_img_label') and self._img_label.winfo_manager():
            self._img_label.pack_forget()
        if not self.text.winfo_manager():
            self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    SIDEBAR_WIDTH = 320

    def __init__(self, doc_store, processor):
        super().__init__()
        self.doc_store = doc_store
        self.processor = processor
        self.logger: Logger = getattr(processor, "logger", Logger())
        self.current_doc_id: int | None = None
        self.history: list[int] = []

        self._last_pil_img: Image.Image | None = None
        self._last_tk_img: ImageTk.PhotoImage | None = None
        self._image_enlarged: bool = False

        self.title("Engelbart Journal – DemoKit")
        self.geometry("1200x800")
        self.columnconfigure(0, minsize=self.SIDEBAR_WIDTH, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_pane()
        self._build_context_menu()

        # --- Menubar ---
        menubar = tk.Menu(self)
        # File menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Import", command=self._import_doc)
        filemenu.add_command(label="Export Current", command=self._export_doc)
        filemenu.add_separator()
        filemenu.add_command(label="Export to Intraweb", command=self.export_and_launch_server)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        # View menu (adds TreeView entry + shortcut)
        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Document Tree\tCtrl+T", command=self.on_tree_button)
        menubar.add_cascade(label="View", menu=viewmenu)
        self.config(menu=menubar)
        # Keyboard shortcut
        self.bind("<Control-t>", lambda e: self.on_tree_button())

        self._refresh_sidebar()

    def _handle_strings(self):
        doc_id = self.current_doc_id
        if doc_id is None:
            return
        self._render_document(doc_id)

    def _build_sidebar(self):
        frame = tk.Frame(self)
        frame.grid(row=0, column=0, sticky="nswe")
        self.sidebar = ttk.Treeview(frame, columns=("ID","Title","Description"), show="headings")
        for col,w in (("ID",60),("Title",120),("Description",160)):
            self.sidebar.heading(col, text=col)
            self.sidebar.column(col, width=w, anchor="w", stretch=(col=="Description"))
        self.sidebar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Scrollbar(frame, orient="vertical", command=self.sidebar.yview).pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar.bind("<<TreeviewSelect>>", self._on_select)
        self.sidebar.bind("<Delete>", lambda e: self._on_delete_clicked())

    def _on_select(self, event):
        sel = self.sidebar.selection()
        if not sel:
            return
        item = self.sidebar.item(sel[0])
        try:
            nid = int(item["values"][0])
        except (ValueError,TypeError):
            return
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = nid
        doc = self.doc_store.get_document(nid)
        if doc:
            self._render_document(doc)

    # keep delete handler above main pane to avoid edge cases
    def _on_delete_clicked(self):
        """Delete the currently selected document."""
        sel = self.sidebar.selection()
        if not sel:
            messagebox.showwarning("Delete", "No document selected.")
            return
        item = self.sidebar.item(sel[0])
        try:
            nid = int(item["values"][0])
        except (ValueError, TypeError):
            messagebox.showerror("Delete", "Invalid document ID.")
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete document ID {nid}?"):
            return
        doc = self.doc_store.get_document(nid)
        self.doc_store.delete_document(nid)
        self._refresh_sidebar()
        self.text.delete("1.0", tk.END)
        self.img_label.configure(image="")
        self.current_doc_id = None
        self._last_pil_img = None
        self._last_tk_img = None
        self._image_enlarged = False
        messagebox.showinfo("Deleted", f"Document {nid} has been deleted.")

    def _build_main_pane(self):
        pane = tk.Frame(self)
        pane.grid(row=0, column=1, sticky="nswe", padx=4, pady=4)
        pane.rowconfigure(0, weight=3)
        pane.rowconfigure(1, weight=1)
        pane.columnconfigure(0, weight=1)

        self.text = tk.Text(pane, wrap="word")
        self.text.grid(row=0, column=0, sticky="nswe")
        self.text.tag_configure("link", foreground="green", underline=True)
        self.text.bind("<Button-3>", self._show_context_menu)
        self.text.bind("<Delete>", lambda e: self._on_delete_clicked())

        self.img_label = tk.Label(pane)
        self.img_label.grid(row=1, column=0, sticky="ew", pady=(8,0))
        self.img_label.bind("<Button-1>", lambda e: self._toggle_image())

        btns = tk.Frame(pane)
        btns.grid(row=2, column=0, sticky="we", pady=(6,0))
        acts = [
            ("TREE", self.on_tree_button),
            ("ASK", self._handle_ask),
            ("BACK", self._go_back),
            ("DELETE", lambda: self._on_delete_clicked()),
            ("IMAGE", self._handle_image),
            ("FLASK", self.export_and_launch_server),
            ("DIR IMPORT", self._import_directory),
            ("SAVE AS TEXT", self._save_binary_as_text),
        ]
        for i,(lbl,cmd) in enumerate(acts):
            ttk.Button(btns, text=lbl, command=cmd).grid(row=0, column=i, sticky="we", padx=(0,4))

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="ASK", command=self._handle_ask)
        self.context_menu.add_command(label="Delete", command=self._on_delete_clicked)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Import", command=self._import_doc)
        self.context_menu.add_command(label="Export", command=self._export_doc)
        self.context_menu.add_command(label="Save Binary As Text", command=self._save_binary_as_text)

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _handle_ask(self):
        try:
            start = self.text.index(tk.SEL_FIRST)
            end   = self.text.index(tk.SEL_LAST)
            selected_text = self.text.get(start, end)
        except tk.TclError:
            messagebox.showwarning("ASK","Please select some text first.")
            return
        cid = self.current_doc_id
        def on_success(nid):
            messagebox.showinfo("ASK",f"Created new document {nid}.")
            self._refresh_sidebar()
            # replace selection with link
            self.text.delete(start,end)
            link_md = f"[{selected_text}](doc:{nid})"
            self.text.insert(start, link_md)
            full = self.text.get("1.0",tk.END)
            # ---- if body is bytes and not an image, show placeholder instead of parsing ----
            doc = self.doc_store.get_document(nid)
            if isinstance(doc["body"], bytes):
                self.text.insert(tk.END, "[binary document]")
                return
            hypertext_parser.parse_links(self.text, full, self._on_link_click)
        prefix = simpledialog.askstring("Prefix","Optional prefix:",initialvalue="Please expand:")
        self.processor.query_ai(selected_text, cid, on_success, lambda *_:None,
                                 prefix=prefix, sel_start=None, sel_end=None)

    def _go_back(self):
        if not self.history:
            messagebox.showinfo("BACK","No history.")
            return
        prev = self.history.pop()
        self.current_doc_id = prev
        doc = self.doc_store.get_document(prev)
        if doc:
            self._render_document(doc)
        else:
            messagebox.showerror("BACK",f"Document {prev} not found.")

    # ---- TreeView wiring ----
    def on_tree_button(self):
        """Open the TreeView window using the current document as the root (if any)."""

        class _DocStoreRepo:
            """Adapter that derives parent→children from green links like (doc:123)."""
            def __init__(self, ds):
                self.ds = ds
                self._roots_cache = None

            def _mk_node(self, d):
                if not d:
                    return None
                if isinstance(d, dict):
                    return type("DocNodeShim", (), {
                        "id": d.get("id"),
                        "title": d.get("title") or "(untitled)",
                        "parent_id": d.get("parent_id"),
                    })()
                # tuple/list fallback: (id, title, body, ...)
                did = d[0] if len(d) > 0 else None
                title = d[1] if len(d) > 1 else ""
                return type("DocNodeShim", (), {"id": did, "title": title or "(untitled)", "parent_id": None})()

            def get_doc(self, doc_id: int):
                return self._mk_node(self.ds.get_document(doc_id))

            def _body(self, doc):
                return doc["body"] if isinstance(doc, dict) else (doc[2] if len(doc) > 2 else "")

            def _children_from_links(self, parent_id):
                d = self.ds.get_document(parent_id)
                if not d:
                    return []
                body = self._body(d)
                if isinstance(body, (bytes, bytearray)):
                    return []
                ids = [int(m) for m in re.findall(r"\(doc:(\d+)\)", body)]
                out = []
                for cid in ids:
                    nd = self.ds.get_document(cid)
                    if nd:
                        out.append(self._mk_node(nd))
                out.sort(key=lambda n: n.id)
                return out

            def get_children(self, parent_id):
                # No parent_id column in the DB, so derive from green-link references
                if parent_id is None:
                    if self._roots_cache is None:
                        all_ids = [row["id"] for row in self.ds.get_document_index()]
                        referenced = set()
                        for row in self.ds.get_document_index():
                            d = self.ds.get_document(row["id"])
                            body = self._body(d)
                            if isinstance(body, (bytes, bytearray)):
                                continue
                            referenced.update(int(m) for m in re.findall(r"\(doc:(\d+)\)", body))
                        # roots = docs never referenced by any other doc
                        roots = [self._mk_node(self.ds.get_document(i)) for i in all_ids if i not in referenced]
                        if not roots:  # fallback: show all if everything is referenced
                            roots = [self._mk_node(self.ds.get_document(i)) for i in all_ids]
                        self._roots_cache = [n for n in roots if n]
                        self._roots_cache.sort(key=lambda n: n.id)
                    return list(self._roots_cache)
                else:
                    return self._children_from_links(parent_id)

        repo = _DocStoreRepo(self.doc_store)
        root_id = self.current_doc_id
        open_tree_view(self, repo=repo, on_open_doc=self._on_link_click, root_doc_id=root_id)

    def _handle_image(self):
        try:
            start = self.text.index(tk.SEL_FIRST)
            end   = self.text.index(tk.SEL_LAST)
            prompt = self.text.get(start,end).strip()
        except tk.TclError:
            messagebox.showwarning("IMAGE","Please select some text first.")
            return
        def wrk():
            try:
                pil = image_generator.generate_image(prompt)
                self._last_pil_img = pil
                thumb = pil.copy()
                thumb.thumbnail((800,400))
                self._last_tk_img = ImageTk.PhotoImage(thumb)
                self._image_enlarged = False
                self.after(0,lambda: self.img_label.configure(image=self._last_tk_img))
            except Exception as e:
                self.after(0,lambda: messagebox.showerror("Image Error",str(e)))
        threading.Thread(target=wrk,daemon=True).start()

    def _toggle_image(self):
        if not self._last_pil_img:
            return
        if not self._image_enlarged:
            win = tk.Toplevel(self)
            win.title("Image Preview")
            sw,sh=self.winfo_screenwidth(),self.winfo_screenheight()
            iw,ih=self._last_pil_img.size
            win.geometry(f"{min(iw,sw)}x{min(ih,sh)}")
            canvas=tk.Canvas(win)
            hbar=ttk.Scrollbar(win,orient='horizontal',command=canvas.xview)
            vbar=ttk.Scrollbar(win,orient='vertical',command=canvas.yview)
            canvas.configure(xscrollcommand=hbar.set,yscrollcommand=vbar.set,
                             scrollregion=(0,0,iw,ih))
            canvas.grid(row=0,column=0,sticky='nsew')
            hbar.grid(row=1,column=0,sticky='we')
            vbar.grid(row=0,column=1,sticky='ns')
            win.grid_rowconfigure(0,weight=1)
            win.grid_columnconfigure(0,weight=1)
            tk_img=ImageTk.PhotoImage(self._last_pil_img)
            canvas.create_image(0,0,anchor='nw',image=tk_img)
            canvas.image=tk_img
            win.bind("<Button-1>",lambda e: self._toggle_image())
            self._image_enlarged = True
        else:
            default=f"document_{self.current_doc_id}.png"
            path=filedialog.asksaveasfilename(
                title="Save Image",initialfile=default,
                defaultextension=".png",filetypes=[("PNG","*.png"),("All Files","*.*")]
            )
            if path:
                try:
                    self._last_pil_img.save(path)
                    messagebox.showinfo("Save Image",f"Image saved to:\n{path}")
                except Exception as e:
                    messagebox.showerror("Save Image",f"Error saving image:{e}")
            self._image_enlarged=False

    def _import_doc(self):
        path=filedialog.askopenfilename(title="Import",filetypes=[("Text","*.txt"),("All","*.*")])
        if not path:
            return
        body=Path(path).read_text(encoding="utf-8")
        title=Path(path).stem
        nid=self.doc_store.add_document(title,body)
        self.logger.info(f"Imported {nid}")
        self._refresh_sidebar()
        doc=self.doc_store.get_document(nid)
        if doc:
            self._render_document(doc)

    def _export_doc(self):
        if self.current_doc_id is None:
            messagebox.showwarning("Export","No document loaded.")
            return
        doc=self.doc_store.get_document(self.current_doc_id)
        if not doc:
            messagebox.showerror("Export","Not found.")
            return
        default=f"document_{self.current_doc_id}.txt"
        path=filedialog.asksaveasfilename(
            title="Export",initialfile=default,defaultextension=".txt",
            filetypes=[("Text","*.txt"),("All","*.*")]
        )
        if not path:
            return
        Path(path).write_text(doc["body"],encoding="utf-8")
        messagebox.showinfo("Export",f"Saved to:\n{path}")

    def _import_directory(self):
        dir_path = filedialog.askdirectory(title="Select Folder to Import")
        if not dir_path:
            return
        imported, skipped = import_text_files_from_directory(dir_path, self.doc_store)
        msg = f"Imported {imported} file(s), skipped {skipped}."
        print("[INFO]", msg)
        messagebox.showinfo("Directory Import", msg)
        self._refresh_sidebar()
    
    def export_and_launch_server(self):
        export_path = Path("exported_docs")
        export_path.mkdir(exist_ok=True)
        for doc in self.doc_store.get_document_index():
            data = dict(self.doc_store.get_document(doc["id"]))
            if data:
                data = sanitize_doc(data)
                with open(export_path / f"{data['id']}.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        def launch():
            fp = Path("modules") / "flask_server.py"
            if fp.exists():
                subprocess.Popen([sys.executable, str(fp)])
        threading.Thread(target=launch, daemon=True).start()
        messagebox.showinfo("Server Started", "Flask server launched at http://127.0.0.1:5050")

    def _save_binary_as_text(self):
        selected_item = self.sidebar.selection() 
        if not selected_item:
            return  # nothing selected
        doc_id_str = self.sidebar.item(selected_item, 'values')[0]
        if not doc_id_str.isdigit():
            print(f"Warning: selected text is not a valid integer '{doc_id_str}'")
            return
        doc_id = int(doc_id_str)
        doc = self.doc_store.get_document(doc_id)
        if not doc or len(doc) < 3:
            return
        body = doc[2]
        # convert only if binary
        if isinstance(body, bytes) or ('\x00' in str(body)):
            print("Binary detected, converting to text using render_binary_as_text.")
            body = render_binary_as_text(body)
            self.doc_store.update_document(doc_id, body)
            self._render_document(self.doc_store.get_document(doc_id))
        else:
            print("Document is already text. Skipping overwrite.")
        content = self.processor.get_strings_content(doc_id)
        self.doc_store.update_document(doc_id, content)
        doc = self.doc_store.get_document(doc_id)
        self._render_document(doc)

    def _refresh_sidebar(self):
        self.sidebar.delete(*self.sidebar.get_children())
        for doc in self.doc_store.get_document_index():
            self.sidebar.insert("","end", values=(doc["id"],doc["title"],doc["description"]))

    def _render_document(self, doc):
        """Render a document once (no duplicate inserts), parse green links."""
        # Normalize doc body
        body = doc.get("body") if isinstance(doc, dict) else (doc[2] if len(doc) > 2 else "")
        self.text.delete("1.0", tk.END)
        # Guard 1: bytes
        if isinstance(body, (bytes, bytearray)):
            self.text.insert(tk.END, "[binary document]")
            return
        # Guard 2: oversized
        if isinstance(body, str) and len(body) > 200_000:
            self.text.insert(tk.END, "[large binary-like document]")
            return
        # Show and parse
        self.text.insert(tk.END, body or "")
        hypertext_parser.parse_links(self.text, body or "", self._on_link_click)

    def _on_link_click(self, doc_id):
        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)
        self.current_doc_id = doc_id
        doc = self.doc_store.get_document(doc_id)
        if doc:
            self._render_document(doc)

def sanitize_doc(doc):
    if isinstance(doc["body"], bytes):
        try:
            doc["body"] = doc["body"].decode("utf-8")
        except UnicodeDecodeError:
            doc["body"] = doc["body"].decode("utf-8", errors="replace")
    return doc

