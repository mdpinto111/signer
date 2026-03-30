"""
PDF Signer - Places a PNG signature next to the Hebrew word חתימה in a PDF.
Usage: python sign_pdf.py [pdf] [signature.png] [options]

Options:
  --output OUTPUT     Output file path (default: input_signed.pdf)
  --width WIDTH       Signature width in points (default: 120)
  --height HEIGHT     Signature height in points (default: 40)
  --offset-x X        Horizontal offset from the word (default: 5)
  --offset-y Y        Vertical offset from the word top (default: -2)
"""

import argparse
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf"])
    import fitz

KEYWORD = "חתימה"


def find_keyword_rects(page):
    """Return merged bounding boxes per occurrence of the keyword on this page."""
    rects = page.search_for(KEYWORD)
    if not rects:
        return []

    # search_for may split the word into multiple rects (per glyph) — merge them
    # Group rects that share the same y-band (same text line)
    merged = []
    rects_sorted = sorted(rects, key=lambda r: (round(r.y0), r.x0))
    current = fitz.Rect(rects_sorted[0])
    for r in rects_sorted[1:]:
        if abs(r.y0 - current.y0) < 4:  # same line
            current = current | r
        else:
            merged.append(current)
            current = fitz.Rect(r)
    merged.append(current)
    return merged


def sign_pdf(
    pdf_path: str,
    signature_path: str,
    output_path: str = None,
    sig_width: float = 120,
    sig_height: float = 40,
    offset_x: float = 5,
    offset_y: float = -2,
):
    pdf_path = Path(pdf_path)
    signature_path = Path(signature_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not signature_path.exists():
        raise FileNotFoundError(f"Signature PNG not found: {signature_path}")

    if output_path is None:
        output_path = pdf_path.parent / f"{pdf_path.stem}_signed{pdf_path.suffix}"
    output_path = Path(output_path)

    doc = fitz.open(str(pdf_path))
    placed = 0

    for page_num, page in enumerate(doc):
        keyword_rects = find_keyword_rects(page)
        for kw_rect in keyword_rects:
            # Hebrew is RTL: place the signature to the LEFT of the word
            # (lower x values). Center it vertically on the word.
            word_center_y = (kw_rect.y0 + kw_rect.y1) / 2
            sig_x0 = kw_rect.x0 - sig_width - offset_x
            sig_y0 = kw_rect.y0 + offset_y
            sig_x1 = kw_rect.x0 - offset_x
            sig_y1 = sig_y0 + sig_height

            # Clamp to page bounds
            page_rect = page.rect
            sig_x0 = max(sig_x0, page_rect.x0 + 5)
            sig_x1 = min(sig_x1, page_rect.x1 - 5)

            sig_rect = fitz.Rect(sig_x0, sig_y0, sig_x1, sig_y1)
            page.insert_image(sig_rect, filename=str(signature_path))
            print(f"  Page {page_num + 1}: placed signature at {sig_rect} (next to '{KEYWORD}' at {kw_rect})")
            placed += 1

    if placed == 0:
        print(f"Warning: word '{KEYWORD}' not found in any page. No signature placed.")
    else:
        print(f"\nTotal signatures placed: {placed}")

    doc.save(str(output_path))
    print(f"Signed PDF saved to: {output_path}")
    return str(output_path)


def find_file(folder: Path, extensions: list) -> Path | None:
    for ext in extensions:
        matches = sorted(folder.glob(f"*{ext}"))
        if matches:
            return matches[0]
    return None


def main():
    parser = argparse.ArgumentParser(description=f"Sign a PDF next to '{KEYWORD}'.")
    parser.add_argument("pdf", nargs="?", help="Path to the PDF file")
    parser.add_argument("signature", nargs="?", help="Path to the PNG signature")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--width", type=float, default=120, help="Signature width in points (default: 120)")
    parser.add_argument("--height", type=float, default=40, help="Signature height in points (default: 40)")
    parser.add_argument("--offset-x", type=float, default=5, dest="offset_x",
                        help="Gap between signature and word in points (default: 5)")
    parser.add_argument("--offset-y", type=float, default=-2, dest="offset_y",
                        help="Vertical offset from word top in points (default: -2)")
    args = parser.parse_args()

    root = Path(__file__).parent
    pdf_path = args.pdf or find_file(root, [".pdf"])
    sig_path = args.signature or find_file(root, [".png"])

    if not pdf_path:
        print("Error: No PDF found. Pass it as argument or place it in the script folder.")
        sys.exit(1)
    if not sig_path:
        print("Error: No PNG signature found. Pass it as argument or place it in the script folder.")
        sys.exit(1)

    sign_pdf(
        pdf_path=pdf_path,
        signature_path=sig_path,
        output_path=args.output,
        sig_width=args.width,
        sig_height=args.height,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
    )


if __name__ == "__main__":
    main()
