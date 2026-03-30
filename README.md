# PDF Signer

A Python desktop app to visually sign and annotate PDF documents — click to place your signature image or add text anywhere on any page.

---

## Features

- **Visual placement** — signature and text follow your cursor before you place them, so you see exactly where they'll land
- **Drag to resize** — draw a rectangle on the PDF to set the signature size on the fly
- **Hebrew / RTL support** — Hebrew text is placed with correct right-to-left alignment
- **Transparent signature** — near-white pixels in the PNG are automatically made transparent so the signature blends over existing content
- **Multi-page PDF** — all pages are rendered in a continuous scroll view
- **Any image format** — PNG, JPG, BMP, TIFF supported as signature
- **Undo / Remove** — undo the last placement or remove any specific item from the list

---

## Requirements

```
Python 3.10+
pymupdf
Pillow
```

Install dependencies:

```bash
pip install pymupdf Pillow
```

---

## Usage

```bash
python app.py
```

The app auto-loads the first PDF and PNG found in the same folder.

### Placing a signature

1. Select **Place Signature** in the toolbar
2. Click **Browse signature file...** to load a PNG/JPG image
3. Adjust **W / H** spinboxes or just drag on the PDF to draw the area
4. Click (or drag) on the PDF where you want the signature

### Adding text

1. Select **Add Text** in the toolbar
2. Type your text in the **Text to insert** field (Hebrew and Latin supported)
3. Adjust font size and color
4. Click on the PDF where you want the text — it follows your cursor live

### Saving

Click **Save PDF** → choose output file → done.

---

## File structure

```
app.py          Main application
sign_pdf.py     CLI script (auto-places signature next to the word חתימה)
sign.png        Default signature image (replace with your own)
```

---

## Tips

- **Undo** removes the last placement; **Remove selected** removes any item from the list
- **Go to page** field at the bottom lets you jump to a specific page
- Signature background is auto-stripped — no need to pre-edit your PNG
- For best results use a PNG with a transparent or white background
