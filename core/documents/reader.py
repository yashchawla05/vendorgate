"""Turn an uploaded file into what the extractors need: text (if it has a text
layer) and page images (if it does not, i.e. a scan or a photo).

pdfplumber reads the text layer; pypdfium2 rasterises pages. PyMuPDF was avoided
because it is AGPL-licensed.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

# Below this many characters (after removing boilerplate) we treat a PDF as a scan.
MIN_TEXT_CHARS = 40
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
RENDER_DPI = 150  # A4 at 150 dpi = 1241x1754 px: legible and within vision size limits
MAX_IMAGE_EDGE = 2000


@dataclass
class DocumentContent:
    filename: str
    sha256: str
    kind: str  # "pdf" | "image" | "unsupported"
    page_count: int = 0
    pages_read: int = 0
    text: str = ""
    images: list[bytes] = field(default_factory=list)  # JPEG bytes, one per page read
    error: str = ""

    @property
    def has_text(self) -> bool:
        return len(self.text.strip()) >= MIN_TEXT_CHARS


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _to_jpeg(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def read_document(path: Path, max_pages: int = 4) -> DocumentContent:
    """Read at most `max_pages` pages (cost guard). Never raises: errors go in .error."""
    data = path.read_bytes()
    content = DocumentContent(filename=path.name, sha256=sha256_bytes(data), kind="unsupported")
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            content.kind = "pdf"
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                content.page_count = len(pdf.pages)
                pages = pdf.pages[:max_pages]
                content.pages_read = len(pages)
                content.text = "\n".join((p.extract_text() or "") for p in pages)
            if not content.has_text:
                # No usable text layer: rasterise for vision.
                doc = pdfium.PdfDocument(data)
                for i in range(content.pages_read):
                    content.images.append(_to_jpeg(doc[i].render(scale=RENDER_DPI / 72).to_pil()))
        elif suffix in IMAGE_SUFFIXES:
            content.kind = "image"
            content.page_count = content.pages_read = 1
            content.images.append(_to_jpeg(Image.open(io.BytesIO(data))))
        else:
            content.error = f"Unsupported file type '{suffix}'. Upload PDF, JPG or PNG."
    except Exception as exc:  # corrupt or encrypted files must not crash the pipeline
        content.error = f"Could not open file: {type(exc).__name__}: {exc}"
    return content
