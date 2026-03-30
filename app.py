"""
PDF Editor UI - Place signature and text anywhere on a PDF by clicking.
Run: python app.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import io

ZOOM = 1.5  # render scale
DRAG_THRESHOLD = 6  # px — below this, a drag is treated as a click


def is_rtl(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0x0600 <= cp <= 0x06FF:
            return True
    return False


def make_transparent_png(img_path: str) -> bytes:
    """Open image and convert near-white pixels to transparent, return PNG bytes."""
    img = Image.open(img_path).convert("RGBA")
    data = img.getdata()
    new_data = [
        (r, g, b, 0) if (r > 220 and g > 220 and b > 220) else (r, g, b, a)
        for r, g, b, a in data
    ]
    img.putdata(new_data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class PDFEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Signer")
        self.resizable(True, True)

        self.pdf_path: Path | None = None
        self.sig_path: Path | None = None
        self.sig_preview: ImageTk.PhotoImage | None = None
        self.doc: fitz.Document | None = None
        self.page_index = 0
        self.mode = tk.StringVar(value="signature")
        self.mode.trace_add("write", self._on_mode_change)

        self.placements: list[dict] = []
        self._ghost_id = None
        self._rubber_band_id = None
        self._drag_start = None       # (canvas_x, canvas_y) at mousedown
        self._page_offsets: list[int] = []   # y offset of each page in canvas px
        self._page_heights: list[int] = []   # rendered height of each page in px
        self._tk_imgs: list = []             # keep PhotoImage refs alive

        self._build_ui()
        self._auto_load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Browse PDF...", command=self._open_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Radiobutton(toolbar, text="Place Signature", variable=self.mode,
                        value="signature").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(toolbar, text="Add Text", variable=self.mode,
                        value="text").pack(side=tk.LEFT, padx=4)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Undo", command=self._undo).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save PDF", command=self._save).pack(side=tk.RIGHT, padx=2)

        self.status = tk.StringVar(value="Open a PDF to start.")
        ttk.Label(self, textvariable=self.status, anchor=tk.W,
                  padding=(8, 3), relief=tk.SUNKEN).pack(side=tk.BOTTOM, fill=tk.X)

        nav = ttk.Frame(self, padding=4)
        nav.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(nav, text="Go to page:").pack(side=tk.LEFT)
        self.page_label = ttk.Label(nav, text="")
        self.page_label.pack(side=tk.LEFT, padx=6)
        self._goto_var = tk.StringVar()
        ge = ttk.Entry(nav, textvariable=self._goto_var, width=4)
        ge.pack(side=tk.LEFT)
        ge.bind("<Return>", self._goto_page)

        # ── Sidebar ──
        sidebar = ttk.Frame(self, padding=6, width=210)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Signature section
        ttk.Label(sidebar, text="Signature", font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Button(sidebar, text="Browse signature file...",
                   command=self._open_sig).pack(fill=tk.X, pady=2)
        self.sig_name_label = ttk.Label(sidebar, text="(none)", foreground="#666",
                                        wraplength=190, justify=tk.LEFT)
        self.sig_name_label.pack(anchor=tk.W)

        ttk.Label(sidebar, text="Preview:", font=("", 8)).pack(anchor=tk.W, pady=(4, 0))
        self.sig_thumb_label = ttk.Label(sidebar, text="", relief=tk.GROOVE,
                                         width=22, anchor=tk.CENTER)
        self.sig_thumb_label.pack(fill=tk.X, ipady=8)

        ttk.Label(sidebar, text="Drag on PDF to resize. Or set manually:",
                  foreground="#555", wraplength=190, justify=tk.LEFT,
                  font=("", 8)).pack(anchor=tk.W, pady=(4, 0))
        sf = ttk.Frame(sidebar)
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="W:").pack(side=tk.LEFT)
        self.sig_w = tk.IntVar(value=120)
        ttk.Spinbox(sf, from_=20, to=600, textvariable=self.sig_w, width=5,
                    command=self._update_sig_preview).pack(side=tk.LEFT, padx=2)
        ttk.Label(sf, text="H:").pack(side=tk.LEFT)
        self.sig_h = tk.IntVar(value=50)
        ttk.Spinbox(sf, from_=10, to=400, textvariable=self.sig_h, width=5,
                    command=self._update_sig_preview).pack(side=tk.LEFT, padx=2)

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Text section
        ttk.Label(sidebar, text="Text", font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(sidebar, text="Text to insert:").pack(anchor=tk.W)
        self.text_var = tk.StringVar()
        self.text_var.trace_add("write", lambda *_: self._clear_ghost())
        ttk.Entry(sidebar, textvariable=self.text_var, width=24,
                  font=("Arial", 10)).pack(fill=tk.X, pady=2)

        tf = ttk.Frame(sidebar)
        tf.pack(fill=tk.X, pady=2)
        ttk.Label(tf, text="Size:").pack(side=tk.LEFT)
        self.font_size = tk.IntVar(value=12)
        fs = ttk.Spinbox(tf, from_=6, to=72, textvariable=self.font_size, width=5)
        fs.pack(side=tk.LEFT, padx=2)
        fs.bind("<ButtonRelease-1>", lambda *_: self._clear_ghost())
        fs.bind("<KeyRelease>", lambda *_: self._clear_ghost())

        cf = ttk.Frame(sidebar)
        cf.pack(fill=tk.X, pady=2)
        ttk.Label(cf, text="Color:").pack(side=tk.LEFT)
        self.font_color = tk.StringVar(value="#000000")
        ce = ttk.Entry(cf, textvariable=self.font_color, width=9)
        ce.pack(side=tk.LEFT, padx=2)
        ce.bind("<KeyRelease>", lambda *_: self._clear_ghost())

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(sidebar, text="Placements", font=("", 10, "bold")).pack(anchor=tk.W)
        self.listbox = tk.Listbox(sidebar, width=26, activestyle="dotbox", height=8)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        ttk.Button(sidebar, text="Remove selected",
                   command=self._remove_selected).pack(fill=tk.X, pady=2)

        # ── Canvas ──
        frame = ttk.Frame(self)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        hs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        vs = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = tk.Canvas(frame, bg="#666", cursor="crosshair",
                                xscrollcommand=hs.set, yscrollcommand=vs.set)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        hs.config(command=self.canvas.xview)
        vs.config(command=self.canvas.yview)

        self.canvas.bind("<ButtonPress-1>",   self._on_mouse_down)
        self.canvas.bind("<B1-Motion>",        self._on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self._on_mouse_up)
        self.canvas.bind("<Motion>",           self._on_mouse_move)
        self.canvas.bind("<Leave>",            self._on_mouse_leave)

    # ── File loading ──────────────────────────────────────────────────────────

    def _auto_load(self):
        root = Path(__file__).parent
        pdfs = [p for p in sorted(root.glob("*.pdf")) if "_signed" not in p.stem
                and "test_" not in p.stem]
        pngs = sorted(root.glob("*.png"))
        if pdfs:
            self._load_pdf(pdfs[0])
        if pngs:
            self._load_sig(pngs[0])

    def _open_pdf(self):
        initial = str(Path.home() / "Desktop") if (Path.home() / "Desktop").exists() else str(Path.home())
        p = filedialog.askopenfilename(
            title="Select a PDF to sign",
            initialdir=initial,
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if p:
            self._load_pdf(Path(p))

    def _open_sig(self):
        p = filedialog.askopenfilename(filetypes=[
            ("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.gif"),
            ("All files", "*.*"),
        ])
        if p:
            self._load_sig(Path(p))

    def _load_pdf(self, path: Path):
        self.pdf_path = path
        self.doc = fitz.open(str(path))
        self.page_index = 0
        self.placements.clear()
        self.listbox.delete(0, tk.END)
        self._render_all_pages()
        self._update_status()

    def _load_sig(self, path: Path):
        self.sig_path = path
        self.sig_name_label.config(text=path.name)
        self._update_sig_preview()
        self._update_status()

    def _update_sig_preview(self):
        if not self.sig_path:
            return
        w, h = self.sig_w.get(), self.sig_h.get()
        try:
            img = Image.open(str(self.sig_path)).convert("RGBA")
            thumb = img.copy()
            thumb.thumbnail((190, 60), Image.LANCZOS)
            self._thumb_tk = ImageTk.PhotoImage(thumb)
            self.sig_thumb_label.config(image=self._thumb_tk, text="")
            ghost_img = img.resize((max(1, int(w * ZOOM)), max(1, int(h * ZOOM))), Image.LANCZOS)
            self.sig_preview = ImageTk.PhotoImage(ghost_img)
        except Exception as e:
            self.status.set(f"Error loading signature: {e}")

    def _update_status(self):
        parts = []
        if self.pdf_path:
            parts.append(f"PDF: {self.pdf_path.name} ({len(self.doc)}p)")
        if self.sig_path:
            parts.append(f"SIG: {self.sig_path.name}")
        hint = ("Drag on PDF to place+resize signature."
                if self.mode.get() == "signature"
                else "Click on PDF to place text.")
        self.status.set("  |  ".join(parts) + f"   -> {hint}" if parts else hint)

    # ── Rendering ────────────────────────────────────────────────────────────

    GAP = 12  # px gap between pages

    def _render_all_pages(self):
        if not self.doc:
            return
        self.canvas.delete("all")
        self._tk_imgs.clear()
        self._page_offsets.clear()
        self._page_heights.clear()
        self._ghost_id = None
        self._rubber_band_id = None
        self._drag_start = None

        mat = fitz.Matrix(ZOOM, ZOOM)
        y_cursor = 0
        max_w = 0

        for page in self.doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pil_img = Image.open(io.BytesIO(pix.tobytes("ppm")))
            tk_img = ImageTk.PhotoImage(pil_img)
            self._tk_imgs.append(tk_img)
            self._page_offsets.append(y_cursor)
            self._page_heights.append(pil_img.height)
            self.canvas.create_image(0, y_cursor, anchor=tk.NW, image=tk_img, tags="page")
            y_cursor += pil_img.height + self.GAP
            max_w = max(max_w, pil_img.width)

        total_h = y_cursor - self.GAP
        self.canvas.config(scrollregion=(0, 0, max_w, total_h))
        self._redraw_overlays()
        n = len(self.doc)
        self.page_label.config(text=f"{n} page{'s' if n > 1 else ''}")

    def _page_at(self, canvas_y: float) -> int:
        """Return page index for a given canvas y coordinate."""
        for i, (off, h) in enumerate(zip(self._page_offsets, self._page_heights)):
            if off <= canvas_y < off + h:
                return i
        return len(self.doc) - 1  # below last page → last page

    def _canvas_to_pdf(self, canvas_x: float, canvas_y: float):
        """Convert canvas coords to (page_index, pdf_x, pdf_y)."""
        page_i = self._page_at(canvas_y)
        pdf_x = canvas_x / ZOOM
        pdf_y = (canvas_y - self._page_offsets[page_i]) / ZOOM
        return page_i, pdf_x, pdf_y

    def _pdf_to_canvas(self, page_i: int, pdf_x: float, pdf_y: float):
        """Convert PDF coords to canvas coords."""
        return pdf_x * ZOOM, self._page_offsets[page_i] + pdf_y * ZOOM

    def _redraw_overlays(self):
        self.canvas.delete("overlay")
        for i, p in enumerate(self.placements):
            if p["page"] >= len(self._page_offsets):
                continue
            x0, y0 = self._pdf_to_canvas(p["page"], p["cx"], p["cy"])
            if p["type"] == "signature":
                w = p["w"] * ZOOM
                h = p["h"] * ZOOM
                if "_img_tk" not in p or p.get("_img_size") != (int(w), int(h)):
                    try:
                        img = Image.open(p["path"]).convert("RGBA")
                        img = img.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                        p["_img_tk"] = ImageTk.PhotoImage(img)
                        p["_img_size"] = (int(w), int(h))
                    except Exception:
                        p["_img_tk"] = None
                if p.get("_img_tk"):
                    self.canvas.create_image(x0, y0, anchor=tk.NW,
                                             image=p["_img_tk"], tags="overlay")
                self.canvas.create_rectangle(
                    x0, y0, x0 + w, y0 + h,
                    outline="#2196F3", width=1, dash=(4, 2), tags="overlay")
                self.canvas.create_text(
                    x0 + 3, y0 + 2, anchor=tk.NW, text=str(i + 1),
                    fill="#2196F3", font=("", 7, "bold"), tags="overlay")
            else:
                rtl = is_rtl(p["text"])
                anchor = tk.NE if rtl else tk.NW
                self.canvas.create_text(
                    x0, y0, anchor=anchor, text=p["text"],
                    fill=p.get("color", "#000000"),
                    font=("Arial", max(6, int(p["size"] * ZOOM / 1.5))),
                    tags="overlay")

    # ── Ghost ────────────────────────────────────────────────────────────────

    def _clear_ghost(self):
        if self._ghost_id:
            self.canvas.delete(self._ghost_id)
            self._ghost_id = None

    def _on_mouse_move(self, event):
        if self._drag_start:
            return  # dragging — handled by _on_drag
        mode = self.mode.get()
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        if mode == "signature":
            if not self.sig_preview:
                self._clear_ghost()
                return
            if self._ghost_id:
                self.canvas.coords(self._ghost_id, cx, cy)
            else:
                self._ghost_id = self.canvas.create_image(
                    cx, cy, anchor=tk.NW, image=self.sig_preview, tags="ghost")

        elif mode == "text":
            text = self.text_var.get()
            if not text:
                self._clear_ghost()
                return
            color = self.font_color.get() or "#000000"
            size = max(6, int(self.font_size.get() * ZOOM / 1.5))
            rtl = is_rtl(text)
            anchor = tk.NE if rtl else tk.NW
            if self._ghost_id:
                self.canvas.coords(self._ghost_id, cx, cy)
                self.canvas.itemconfig(self._ghost_id, text=text, fill=color,
                                       font=("Arial", size), anchor=anchor)
            else:
                self._ghost_id = self.canvas.create_text(
                    cx, cy, anchor=anchor, text=text,
                    fill=color, font=("Arial", size), tags="ghost")
        else:
            self._clear_ghost()
            return

        self.canvas.tag_raise("ghost")

    def _on_mouse_leave(self, event):
        self._clear_ghost()

    def _on_mode_change(self, *_):
        self._clear_ghost()
        self._update_status()

    # ── Mouse drag (signature resize) ────────────────────────────────────────

    def _on_mouse_down(self, event):
        if not self.doc:
            return
        self._drag_start = (self.canvas.canvasx(event.x),
                            self.canvas.canvasy(event.y))
        self._clear_ghost()

    def _on_drag(self, event):
        if not self._drag_start or self.mode.get() != "signature":
            return
        x0, y0 = self._drag_start
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)
        if self._rubber_band_id:
            self.canvas.coords(self._rubber_band_id, x0, y0, x1, y1)
        else:
            self._rubber_band_id = self.canvas.create_rectangle(
                x0, y0, x1, y1,
                outline="#FF5722", width=2, dash=(6, 3), tags="rubber")

    def _on_mouse_up(self, event):
        if not self.doc or not self._drag_start:
            return
        x0, y0 = self._drag_start
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)

        if self._rubber_band_id:
            self.canvas.delete(self._rubber_band_id)
            self._rubber_band_id = None

        self._drag_start = None
        mode = self.mode.get()
        dx, dy = abs(x1 - x0), abs(y1 - y0)

        if mode == "signature":
            if not self.sig_path:
                messagebox.showinfo("No signature", "Click 'Browse signature file...' first.")
                return
            if dx > DRAG_THRESHOLD and dy > DRAG_THRESHOLD:
                rx0, ry0 = min(x0, x1), min(y0, y1)
                w = int(abs(x1 - x0) / ZOOM)
                h = int(abs(y1 - y0) / ZOOM)
                self.sig_w.set(w)
                self.sig_h.set(h)
                self._update_sig_preview()
                page_i, pdf_x, pdf_y = self._canvas_to_pdf(rx0, ry0)
                self._place_signature(page_i, pdf_x, pdf_y, w, h)
            else:
                page_i, pdf_x, pdf_y = self._canvas_to_pdf(x0, y0)
                self._place_signature(page_i, pdf_x, pdf_y,
                                      self.sig_w.get(), self.sig_h.get())

        elif mode == "text":
            page_i, pdf_x, pdf_y = self._canvas_to_pdf(x0, y0)
            self._place_text(page_i, pdf_x, pdf_y)

    def _place_signature(self, page_i, cx, cy, w, h):
        entry = {
            "type": "signature",
            "page": page_i,
            "cx": cx, "cy": cy,
            "w": w, "h": h,
            "path": str(self.sig_path),
        }
        self.placements.append(entry)
        self.listbox.insert(tk.END, f"[SIG] p{page_i + 1}  ({int(cx)},{int(cy)}) {w}x{h}")
        self._redraw_overlays()

    def _place_text(self, page_i, cx, cy):
        text = self.text_var.get().strip()
        if not text:
            messagebox.showinfo("No text", "Type text in the sidebar first.")
            return
        color_hex = self.font_color.get().lstrip("#").ljust(6, "0")[:6]
        try:
            rgb = tuple(int(color_hex[i:i+2], 16) / 255 for i in (0, 2, 4))
        except Exception:
            rgb = (0, 0, 0)
        entry = {
            "type": "text",
            "page": page_i,
            "cx": cx, "cy": cy,
            "text": text,
            "size": self.font_size.get(),
            "color": "#" + color_hex,
            "color_rgb": rgb,
        }
        self.placements.append(entry)
        self.listbox.insert(tk.END, f'[TXT] p{page_i + 1}  "{text[:14]}"')
        self._redraw_overlays()

    # ── Navigation ───────────────────────────────────────────────────────────

    def _goto_page(self, _event=None):
        if not self.doc or not self._page_offsets:
            return
        try:
            n = int(self._goto_var.get()) - 1
        except ValueError:
            return
        n = max(0, min(n, len(self.doc) - 1))
        offset = self._page_offsets[n]
        total_h = self._page_offsets[-1] + self._page_heights[-1]
        self.canvas.yview_moveto(offset / total_h)

    # ── Undo / Remove ────────────────────────────────────────────────────────

    def _undo(self):
        if self.placements:
            self.placements.pop()
            self.listbox.delete(tk.END)
            self._redraw_overlays()

    def _remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.placements.pop(sel[0])
        self.listbox.delete(sel[0])
        self._redraw_overlays()

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save(self):
        if not self.doc or not self.pdf_path:
            messagebox.showerror("Error", "No PDF loaded.")
            return
        if not self.placements:
            messagebox.showinfo("Nothing to save", "Place at least one element first.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=self.pdf_path.stem + "_signed.pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialdir=str(self.pdf_path.parent),
        )
        if not out:
            return

        doc = fitz.open(str(self.pdf_path))
        for p in self.placements:
            page = doc[p["page"]]
            if p["type"] == "signature":
                rect = fitz.Rect(p["cx"], p["cy"],
                                 p["cx"] + p["w"], p["cy"] + p["h"])
                # Transparent background: strip near-white pixels
                sig_bytes = make_transparent_png(p["path"])
                page.insert_image(rect, stream=sig_bytes)
            else:
                rtl = is_rtl(p["text"])
                size = p["size"]
                page_w = float(page.rect.width)
                arial = Path("C:/Windows/Fonts/arial.ttf")

                baseline_y = p["cy"] + size * 0.75
                if rtl:
                    # RTL Hebrew: box from 0 to cx, text-align:right (no dir attr).
                    # PDF viewers apply Unicode BiDi automatically — no need for dir:rtl.
                    # text-align:right aligns text to the box right edge = cx.
                    box = fitz.Rect(0, p["cy"], p["cx"] + 4, p["cy"] + size * 1.8)
                    html = (
                        f'<div style="font-family:Arial,sans-serif;font-size:{size}pt;'
                        f'color:{p["color"]};margin:0;padding:0;'
                        f'line-height:1.0;text-align:right;">{p["text"]}</div>'
                    )
                    page.insert_htmlbox(box, html, archive=fitz.Archive())
                else:
                    # LTR: insert_text with exact position.
                    point = fitz.Point(p["cx"], baseline_y)
                    if arial.exists():
                        page.insert_text(point, p["text"], fontsize=size,
                                         fontfile=str(arial), color=p["color_rgb"])
                    else:
                        page.insert_text(point, p["text"], fontsize=size,
                                         color=p["color_rgb"])

        doc.save(out)
        doc.close()
        messagebox.showinfo("Saved", f"Saved to:\n{out}")


if __name__ == "__main__":
    app = PDFEditor()
    app.mainloop()
