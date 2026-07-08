from pathlib import Path
import re

import fitz


def clean_text(text: str) -> str:
    """Normalize PDF text while preserving readable sentence flow."""
    text = text.replace("-\n", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_pdf_pages(pdf_path: str | Path) -> list[dict]:
    path = Path(pdf_path)
    pages: list[dict] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            pages.append({"page": index, "text": clean_text(page.get_text("text"))})
    return pages
