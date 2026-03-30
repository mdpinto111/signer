# PDF Signer

Visually sign and annotate PDF documents — click to place a signature image or add text anywhere on any page. Available as a **desktop app** (Tkinter) and a **web app** (FastAPI + vanilla JS).

---

## Features

- **Visual placement** — signature and text follow your cursor before you place them
- **Drag to resize** — draw a rectangle on the PDF to set the signature size on the fly
- **Hebrew / RTL support** — Hebrew and Arabic text placed with correct right-to-left alignment
- **Transparent signature** — near-white pixels are automatically stripped so the signature blends cleanly
- **Multi-page PDF** — all pages rendered in a continuous scroll view
- **Any image format** — PNG, JPG, BMP, TIFF supported as signature
- **Undo / Remove** — undo the last placement or delete any specific item

---

## Option 1 — Desktop app

### Requirements

```
Python 3.10+
pymupdf
Pillow
```

```bash
pip install pymupdf Pillow
```

### Run

```bash
python app.py
```

The app auto-loads the first PDF and PNG found in the same folder.

### How to use

**Placing a signature**
1. Select **Place Signature** in the toolbar
2. Click **Browse signature file...** in the sidebar to load an image
3. Set the size with the **W / H** spinboxes, or **drag on the PDF** to draw the area directly
4. Click (or drag) on the PDF page where you want the signature

**Adding text**
1. Select **Add Text** in the toolbar
2. Type your text in the **Text to insert** field in the sidebar (Hebrew supported)
3. Adjust font size and color
4. Click on the PDF — the text preview follows your cursor in real time

**Saving**
Click **Save PDF** → choose output location → done.

**Tips**
- **Undo** removes the last placement; **Remove selected** deletes a specific item from the list
- Type a page number in the **Go to page** field at the bottom to jump to that page
- Signature background is auto-stripped — no need to pre-edit your PNG

---

## Option 2 — Web app

A browser-based version with the same features, built with FastAPI (backend) and vanilla JS (frontend). No installation needed for end users — just open the URL.

### Requirements

```
Python 3.10+
```

```bash
cd web
pip install -r requirements.txt
```

### Run locally

```bash
cd web
python main.py
```

Then open **http://localhost:8000** in your browser.

### How to use (web)

**Load a PDF**
- Click **Open PDF** in the top bar, or drag & drop a PDF onto the canvas

**Placing a signature**
1. Click **Signature** mode (left sidebar)
2. Click **Browse image...** to load your signature file, or drag & drop an image onto the canvas
3. Set **W / H** or drag on the PDF to draw the area
4. Click or drag on the PDF to place the signature

**Adding text**
1. Click **Text** mode (left sidebar)
2. Type your text in the textarea (Hebrew and Latin supported)
3. Adjust font size and color
4. Click on the PDF — the text follows your cursor live

**Saving**
Click **Save PDF** in the top bar → the signed PDF downloads automatically.

**Tips**
- All pages are shown in a continuous scroll — no page flipping
- The × button on each placement in the list removes it individually
- Undo removes the last placement
- Drag & drop works for both PDFs and signature images

### Deploy with Docker

```bash
cd web
docker-compose up --build
```

The app will be available on port **8000**.

To deploy on a server (VPS, cloud), just expose port 8000 or put a reverse proxy (nginx, Caddy) in front of it.

---

## File structure

```
app.py               Desktop app (Tkinter)
sign_pdf.py          CLI script — auto-places signature next to the word חתימה
sign.png             Default signature image (replace with your own)
README.md            This file

web/
├── main.py          FastAPI backend
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```
