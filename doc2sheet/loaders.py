"""Turn PDFs and images into what a vision model needs: page images + any text layer."""

from __future__ import annotations

import base64
import io
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}

# A PDF with fewer characters than this is treated as a scan (no usable text layer).
MIN_TEXT_CHARS = 20

# PDFium is not thread-safe. Rendering is fast compared to the model call, so we
# serialise it and keep the (slow) LLM requests parallel.
_PDFIUM_LOCK = threading.Lock()


class LoaderError(ValueError):
    """The file could not be read (unsupported, corrupted, encrypted...)."""


@dataclass
class LoadedDocument:
    name: str
    images: list[bytes] = field(default_factory=list)  # JPEG bytes, one per page
    text: str = ""  # embedded text layer, empty for scans and photos
    page_count: int = 0  # pages in the source file (may exceed len(images))

    @property
    def truncated(self) -> bool:
        return self.page_count > len(self.images)


def load_document(path: str | Path, *, max_pages: int = 3, max_side: int = 1600) -> LoadedDocument:
    """Load a PDF or image file into page images (and text, for digital PDFs)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise LoaderError(
            f"Unsupported file type '{suffix or path.name}'. Use one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    if not path.is_file():
        raise LoaderError(f"File not found: {path}")
    if suffix == ".pdf":
        with _PDFIUM_LOCK:
            return _load_pdf(path, max_pages=max_pages, max_side=max_side)
    return _load_image(path, max_pages=max_pages, max_side=max_side)


def _load_pdf(path: Path, *, max_pages: int, max_side: int) -> LoadedDocument:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        raise LoaderError(f"Could not open PDF (corrupted or password-protected): {exc}") from exc

    doc = LoadedDocument(name=path.name, page_count=len(pdf))
    texts: list[str] = []
    try:
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            width, height = page.get_size()
            scale = min(3.0, max(1.0, max_side / max(width, height)))
            image = page.render(scale=scale).to_pil()
            doc.images.append(_encode_jpeg(image, max_side))
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range().strip())
            textpage.close()
            page.close()
    finally:
        pdf.close()

    text = "\n\n".join(f"--- page {i + 1} ---\n{t}" for i, t in enumerate(texts) if t)
    doc.text = text if sum(len(t) for t in texts) >= MIN_TEXT_CHARS else ""
    if not doc.images:
        raise LoaderError("PDF has no pages")
    return doc


def _load_image(path: Path, *, max_pages: int, max_side: int) -> LoadedDocument:
    doc = LoadedDocument(name=path.name)
    try:
        with Image.open(path) as img:
            doc.page_count = getattr(img, "n_frames", 1)
            for index, frame in enumerate(ImageSequence.Iterator(img)):
                if index >= max_pages:
                    break
                doc.images.append(_encode_jpeg(ImageOps.exif_transpose(frame.copy()), max_side))
    except (OSError, SyntaxError) as exc:  # PIL raises these for corrupt/unknown data
        raise LoaderError(f"Could not read image: {exc}") from exc
    return doc


def _encode_jpeg(image: Image.Image, max_side: int) -> bytes:
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def to_data_url(jpeg_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
