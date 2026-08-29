"""
Document Tool -- extracts clean, page-mapped text from an uploaded PDF.

Page mapping matters: it is what lets the Evaluation Agent cite a real page
number, and what lets the Validation Tool actually check whether a claimed
quote exists in the source document (see validation_tool.verify_evidence).
Without per-page text, "evidence.page" would be a number the LLM invents.
"""
from dataclasses import dataclass
import fitz  # PyMuPDF


MIN_USABLE_CHARS_PER_DOC = 200   # below this, treat as "no usable text" (likely scanned/image-only)
MIN_USABLE_CHARS_TO_FLAG_PAGE = 10


@dataclass
class ExtractionResult:
    supplier_name: str
    pages: list          # list of {"page": int (1-indexed), "text": str}
    full_text: str        # convenience concatenation, page-tagged
    is_usable: bool
    char_count: int
    warning: str = None


def extract_pdf(file_bytes: bytes, supplier_name: str) -> ExtractionResult:
    """
    Extracts text page-by-page from PDF bytes. Returns ExtractionResult with
    is_usable=False (and a clear warning) if the document looks like a
    scanned/image-only PDF with no usable text layer -- per the brief's
    text-PDF prerequisite, OCR is explicitly out of scope.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        return ExtractionResult(
            supplier_name=supplier_name, pages=[], full_text="", is_usable=False,
            char_count=0, warning=f"Could not open PDF: {e}",
        )

    pages = []
    total_chars = 0
    pages_with_text = 0
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        pages.append({"page": i, "text": text})
        total_chars += len(text)
        if len(text) >= MIN_USABLE_CHARS_TO_FLAG_PAGE:
            pages_with_text += 1
    doc.close()

    is_usable = total_chars >= MIN_USABLE_CHARS_PER_DOC and pages_with_text > 0
    warning = None
    if not is_usable:
        warning = (
            "This PDF does not appear to contain a usable text layer "
            "(scanned/image-only PDFs are not supported -- see the text-PDF "
            "prerequisite). Please upload a text-based PDF."
        )

    full_text = "\n\n".join(f"[PAGE {p['page']}]\n{p['text']}" for p in pages)

    return ExtractionResult(
        supplier_name=supplier_name,
        pages=pages,
        full_text=full_text,
        is_usable=is_usable,
        char_count=total_chars,
        warning=warning,
    )
