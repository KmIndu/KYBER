"""OCR pipeline — extract text from images using Tesseract (if available)
or a built-in heuristic fallback.

The pipeline:
  1. Open image with Pillow
  2. Pre-process (greyscale, contrast)
  3. Run Tesseract OCR (or fallback)
  4. Parse output into structured OCRResult with per-block confidence
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import sys

from PIL import Image, ImageEnhance, ImageFilter

from app.models.reference import OCRBlock, OCRResult

logger = logging.getLogger(__name__)

# ── Locate Tesseract binary ──────────────────────────────────
# On Windows the installer may place it outside the system PATH.
# We check common install locations before giving up.

_WINDOWS_TESSERACT_PATHS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Tesseract-OCR", "tesseract.exe"),
]


def _find_tesseract() -> str | None:
    """Return the path to the tesseract binary, or None."""
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        for p in _WINDOWS_TESSERACT_PATHS:
            if p and os.path.isfile(p):
                return p
    return None


_TESSERACT_CMD = _find_tesseract()
_TESSERACT_AVAILABLE: bool = _TESSERACT_CMD is not None

# Configure pytesseract with discovered path
if _TESSERACT_AVAILABLE and _TESSERACT_CMD:
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
    except ImportError:
        _TESSERACT_AVAILABLE = False


class OCRError(Exception):
    """Raised when OCR extraction fails fatally."""


# ── Public API ────────────────────────────────────────────────


def extract_text_from_image(image_bytes: bytes) -> OCRResult:
    """Run the OCR pipeline on raw image bytes and return structured results.

    Falls back to a basic heuristic extractor if Tesseract is not installed.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise OCRError(f"Cannot open image: {e}") from e

    width, height = img.size
    img = _preprocess(img)

    if _TESSERACT_AVAILABLE:
        return _run_tesseract(img, width, height)

    logger.info(
        "Tesseract not available — using heuristic fallback",
        extra={"stage": "ocr", "event": "tesseract_unavailable"},
    )
    return _heuristic_fallback(img, width, height)


def extract_text_from_bytes_to_str(image_bytes: bytes) -> str:
    """Convenience helper — returns just the raw text string."""
    return extract_text_from_image(image_bytes).raw_text


# ── Pre-processing ────────────────────────────────────────────


def _preprocess(img: Image.Image) -> Image.Image:
    """Convert to greyscale, sharpen, and boost contrast for better OCR."""
    img = img.convert("L")  # greyscale
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(1.8)
    return img


# ── Tesseract backend ────────────────────────────────────────


def _run_tesseract(img: Image.Image, width: int, height: int) -> OCRResult:
    """Run Tesseract via pytesseract and parse per-word confidence data."""
    import pytesseract

    try:
        tsv_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as e:
        raise OCRError(f"Tesseract failed: {e}") from e

    blocks: list[OCRBlock] = []
    total_conf = 0.0
    conf_count = 0

    n_boxes = len(tsv_data.get("text", []))
    for i in range(n_boxes):
        text = str(tsv_data["text"][i]).strip()
        if not text:
            continue
        conf = float(tsv_data["conf"][i])
        if conf < 0:
            conf = 0.0
        normalised_conf = conf / 100.0  # Tesseract uses 0-100

        blocks.append(
            OCRBlock(
                text=text,
                confidence=round(normalised_conf, 3),
                bbox=[
                    tsv_data["left"][i],
                    tsv_data["top"][i],
                    tsv_data["width"][i],
                    tsv_data["height"][i],
                ],
            )
        )
        total_conf += normalised_conf
        conf_count += 1

    raw_text = " ".join(b.text for b in blocks)
    avg = round(total_conf / conf_count, 3) if conf_count else 0.0

    return OCRResult(
        raw_text=raw_text,
        blocks=blocks,
        avg_confidence=avg,
        image_width=width,
        image_height=height,
    )


# ── Heuristic fallback ───────────────────────────────────────
# When Tesseract is not installed, we still want the pipeline to
# function; we'll use Pillow to detect basic image characteristics
# and provide a placeholder OCR result. The real extraction will
# come from the AI enrichment layer that analyses the raw bytes.


def _heuristic_fallback(img: Image.Image, width: int, height: int) -> OCRResult:
    """Generate a minimal OCR result without Tesseract.

    Returns an empty-text result with metadata; the AI enrichment
    step will provide the actual content understanding.
    """
    return OCRResult(
        raw_text="",
        blocks=[],
        avg_confidence=0.0,
        image_width=width,
        image_height=height,
    )
