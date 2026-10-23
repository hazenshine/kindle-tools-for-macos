"""Clean up PDFs exported from Kindle Scribe notebooks.

Every page of an export holds the handwriting as a single image with the
Scribe's 3:4 screen ratio, placed at the top of an A4 page; below it is an
empty strip with the "N of M" page number. PDFs that don't match this layout
are rejected.

For each page the page number is redacted (removed from the file, not just
hidden) and the page is resized to the handwriting image, so the result has
the notebook's own 3:4 page size. The image and the OCR text are untouched.
"""
import re
from pathlib import Path

import pymupdf

FOOTER_RE = re.compile(r"^\d+\s*(?:of|/)\s*\d+$")
BOTTOM_ZONE = 0.90   # the page number sits in the bottom 10% of the page
CENTER_TOL = 0.10    # ...horizontally centered, within 10% of the width


class NotKindleNotebook(Exception):
    pass


class NothingToClean(Exception):
    pass


def _notebook_image_rect(page):
    """Rect of the 3:4 image spanning the page width from the top, or None."""
    for img in page.get_images():
        xref, _, w, h = img[:4]
        if w * 4 != h * 3:
            continue
        for r in page.get_image_rects(xref):
            if abs(r.width - page.rect.width) < 1 and r.y0 < 1:
                return r
    return None


def _footer_rects(page):
    lines = {}
    for x0, y0, x1, y1, word, block, line, _ in page.get_text("words"):
        lines.setdefault((block, line), []).append((pymupdf.Rect(x0, y0, x1, y1), word))
    w, h = page.rect.width, page.rect.height
    for items in lines.values():
        text = " ".join(word for _, word in items)
        rect = pymupdf.Rect()
        for r, _ in items:
            rect |= r
        if (FOOTER_RE.match(text)
                and rect.y0 >= h * BOTTOM_ZONE
                and abs((rect.x0 + rect.x1) / 2 - w / 2) <= w * CENTER_TOL):
            yield rect


def clean(src: Path) -> pymupdf.Document:
    """Clean src in memory and return the open document; the caller saves it
    with save() (which also closes it)."""
    try:
        doc = pymupdf.open(src)
    except Exception:
        raise NotKindleNotebook
    try:
        if not doc.is_pdf or doc.page_count == 0:
            raise NotKindleNotebook
        images = [_notebook_image_rect(p) for p in doc]
        if not all(images):
            raise NotKindleNotebook

        changed = False
        for page, image in zip(doc, images):
            # 1) Remove the page number for good. It would end up outside the
            #    new page size anyway, but would still be in the file.
            rects = list(_footer_rects(page))
            for r in rects:
                page.add_redact_annot(r, fill=False)
            if rects:
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_NONE,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                    text=pymupdf.PDF_REDACT_TEXT_REMOVE,
                )
                changed = True
            # 2) Cut the empty strip: the page becomes exactly the image.
            #    MediaBox is in PDF coordinates (origin bottom-left), the image
            #    rect in page coordinates (origin top-left).
            if page.rect.height - image.y1 > 0.5:
                mb = page.mediabox
                page.set_mediabox(pymupdf.Rect(mb.x0, mb.y1 - image.y1, mb.x1, mb.y1))
                changed = True

        if not changed:
            raise NothingToClean
        return doc
    except Exception:
        doc.close()
        raise


def save(doc: pymupdf.Document, dst: Path) -> None:
    """Save a cleaned document to dst and close it. Writes to a temp file
    first, so dst may even be the original file."""
    tmp = dst.with_name(f".{dst.name}.tmp")
    try:
        doc.save(tmp, garbage=3, deflate=True)
    finally:
        doc.close()
    tmp.replace(dst)
