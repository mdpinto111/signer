"""
PDF Signer Web Backend — FastAPI
"""

import html
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PDF Signer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def revalidate_static(request, call_next):
    # Make browsers revalidate the frontend so a new deploy is picked up at once
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


ZOOM = 1.5
# Text placements are anchored at the top of the line; the baseline sits this
# many font-size units below it. Must match TEXT_ASCENT in static/app.js.
TEXT_ASCENT = 0.8
_baseline_cache: dict[str, tuple[float, float]] = {}
SESSION_ROOT = Path(tempfile.gettempdir()) / "pdf_signer"
SESSION_ROOT.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def session_dir(session_id: str) -> Path:
    d = SESSION_ROOT / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_transparent_png(img_bytes: bytes) -> bytes:
    """Convert near-white pixels to transparent, crop to the ink, return PNG bytes."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    data = img.getdata()
    new_data = [
        (r, g, b, 0) if (r > 220 and g > 220 and b > 220) else (r, g, b, a)
        for r, g, b, a in data
    ]
    img.putdata(new_data)
    # Trim empty margins so the placed box matches the visible signature
    bbox = img.getchannel("A").getbbox()
    if bbox:
        pad = 2
        img = img.crop((
            max(0, bbox[0] - pad), max(0, bbox[1] - pad),
            min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad),
        ))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def is_rtl(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0x0600 <= cp <= 0x06FF:
            return True
    return False


def find_font() -> str | None:
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def html_baseline_offset(css: str, archive, family: str, size: float) -> float:
    """Distance from the top of an htmlbox to the text baseline, in points.

    MuPDF's offset is linear in the font size plus a small constant, so it is
    measured once at two sizes and interpolated.
    """
    key = css + family
    if key not in _baseline_cache:
        def probe(probe_size: float) -> float:
            doc = fitz.open()
            page = doc.new_page()
            page.insert_htmlbox(
                fitz.Rect(0, 0, page.rect.width, 300),
                f'<div style="font-family:{family};font-size:{probe_size}pt;'
                f'line-height:1.0;margin:0;padding:0;">א</div>',
                css=css, archive=archive,
            )
            origins = [
                s["origin"][1]
                for b in page.get_text("dict")["blocks"]
                for l in b.get("lines", [])
                for s in l["spans"]
            ]
            doc.close()
            return origins[0] if origins else probe_size * TEXT_ASCENT

        small, large = probe(10), probe(100)
        slope = (large - small) / 90
        _baseline_cache[key] = (small - 10 * slope, slope)
    const, slope = _baseline_cache[key]
    return const + slope * size


def hex_to_rgb(color: str):
    color = color.lstrip("#").ljust(6, "0")[:6]
    return tuple(int(color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


# ── Pydantic models ───────────────────────────────────────────────────────────

class Placement(BaseModel):
    type: str
    page: int
    cx: float
    cy: float
    w: float = 0
    h: float = 0
    text: str = ""
    size: float = 12
    color: str = "#000000"


class SignRequest(BaseModel):
    session_id: str
    placements: List[Placement]


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/api/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    sdir = session_dir(session_id)

    pdf_bytes = await file.read()
    pdf_path = sdir / "source.pdf"
    pdf_path.write_bytes(pdf_bytes)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(ZOOM, ZOOM)

    pages_info = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_path = sdir / f"page_{i}.png"
        pix.save(str(png_path))
        pages_info.append({
            "width": pix.width,
            "height": pix.height,
            "pdf_width": float(page.rect.width),
            "pdf_height": float(page.rect.height),
        })

    doc.close()

    return {
        "session_id": session_id,
        "pages": pages_info,
        "filename": file.filename or "document.pdf",
    }


@app.post("/api/upload-signature")
async def upload_signature(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    sdir = session_dir(session_id)
    raw = await file.read()

    # Convert to RGBA PNG with transparent background
    transparent = make_transparent_png(raw)
    sig_path = sdir / "signature.png"
    sig_path.write_bytes(transparent)

    return Response(content=transparent, media_type="image/png")


@app.get("/api/page/{session_id}/{page_num}")
async def get_page(session_id: str, page_num: int):
    sdir = session_dir(session_id)
    png_path = sdir / f"page_{page_num}.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(str(png_path), media_type="image/png")


@app.get("/api/signature/{session_id}")
async def get_signature(session_id: str):
    sdir = session_dir(session_id)
    sig_path = sdir / "signature.png"
    if not sig_path.exists():
        raise HTTPException(status_code=404, detail="Signature not found")
    return FileResponse(str(sig_path), media_type="image/png")


@app.post("/api/sign")
async def sign_pdf(req: SignRequest):
    sdir = session_dir(req.session_id)
    pdf_path = sdir / "source.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF session not found")

    sig_path = sdir / "signature.png"
    sig_bytes = sig_path.read_bytes() if sig_path.exists() else None

    doc = fitz.open(str(pdf_path))
    font_path = find_font()

    # Use the same font for RTL (htmlbox) and LTR (insert_text) text
    archive = fitz.Archive()
    css = ""
    if font_path:
        archive.add(Path(font_path).read_bytes(), "signer-font.ttf")
        css = '@font-face {font-family: signer; src: url(signer-font.ttf);}'

    for p in req.placements:
        if p.page < 0 or p.page >= len(doc):
            continue
        page = doc[p.page]

        if p.type == "signature":
            if sig_bytes is None:
                continue
            rect = fitz.Rect(p.cx, p.cy, p.cx + p.w, p.cy + p.h)
            page.insert_image(rect, stream=sig_bytes)

        elif p.type == "text":
            rtl = is_rtl(p.text)
            size = p.size
            cx, cy = p.cx, p.cy
            baseline = cy + size * TEXT_ASCENT

            if rtl:
                # Right edge of the text sits exactly at cx; the box extends far
                # to the left so the line never wraps or gets scaled down.
                family = "signer" if font_path else "sans-serif"
                top = baseline - html_baseline_offset(css, archive, family, size)
                box = fitz.Rect(cx - page.rect.width * 2, top, cx, top + size * 2)
                markup = (
                    f'<div style="font-family:{family};font-size:{size}pt;'
                    f'color:{html.escape(p.color)};margin:0;padding:0;white-space:nowrap;'
                    f'line-height:1.0;text-align:right;">{html.escape(p.text)}</div>'
                )
                page.insert_htmlbox(box, markup, css=css, archive=archive, scale_low=1)
            else:
                point = fitz.Point(cx, baseline)
                rgb = hex_to_rgb(p.color)
                if font_path:
                    # fontfile is ignored by PyMuPDF unless a fontname is given
                    page.insert_text(point, p.text, fontsize=size, fontname="signer",
                                     fontfile=font_path, color=rgb)
                else:
                    page.insert_text(point, p.text, fontsize=size, color=rgb)

    out_buf = io.BytesIO()
    doc.save(out_buf)
    doc.close()
    out_buf.seek(0)

    return StreamingResponse(
        out_buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=signed.pdf"},
    )


# ── Static frontend ───────────────────────────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
