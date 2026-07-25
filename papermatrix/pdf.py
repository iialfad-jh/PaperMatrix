import re
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import fitz


TABLE_CELL_MAX_CHARS = 500
TEXT_TABLE_MAX_PAGE_HEIGHT_RATIO = 0.7


def clean_text(text: str) -> str:
    """Normalize PDF text while preserving readable sentence flow."""
    text = text.replace("-\n", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_table_cell(value: Any) -> str:
    text = clean_text(str(value or ""))
    if len(text) <= TABLE_CELL_MAX_CHARS:
        return text
    return text[: TABLE_CELL_MAX_CHARS - 3].rstrip() + "..."


def _normalize_row(row: list[Any], width: int) -> list[str]:
    cells = [_clean_table_cell(value) for value in row[:width]]
    return cells + [""] * (width - len(cells))


def _copy_table(
    table: Any,
    page_number: int,
    table_index: int,
    strategy: str,
    page_height: float | None = None,
) -> dict | None:
    extracted = table.extract()
    if not isinstance(extracted, list) or not extracted:
        return None
    raw_rows = [row for row in extracted if isinstance(row, (list, tuple))]
    width = max((len(row) for row in raw_rows), default=0)
    if width < 2:
        return None

    rows = [_normalize_row(list(row), width) for row in raw_rows]
    header_names = getattr(getattr(table, "header", None), "names", None)
    if isinstance(header_names, (list, tuple)) and any(value for value in header_names):
        header = _normalize_row(list(header_names), width)
        data_rows = rows[1:] if rows and rows[0] == header else rows
    else:
        header = rows[0]
        data_rows = rows[1:]
    header = [value or f"Column {index + 1}" for index, value in enumerate(header)]
    data_rows = [row for row in data_rows if any(row)]
    if not data_rows:
        return None

    bbox = getattr(table, "bbox", None)
    copied_bbox = [round(float(value), 2) for value in bbox] if bbox is not None else None
    if (
        strategy == "text"
        and copied_bbox is not None
        and page_height
        and (copied_bbox[3] - copied_bbox[1]) / page_height > TEXT_TABLE_MAX_PAGE_HEIGHT_RATIO
    ):
        return None
    return {
        "page": page_number,
        "table_index": table_index,
        "strategy": strategy,
        "bbox": copied_bbox,
        "header": header,
        "rows": data_rows,
    }


def _extract_page_tables(page: Any, page_number: int) -> list[dict]:
    find_tables = getattr(page, "find_tables", None)
    if find_tables is None:
        return []

    for strategy, kwargs in (("lines", {}), ("text", {"strategy": "text"})):
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                finder = find_tables(**kwargs)
            found_tables = list(getattr(finder, "tables", finder))
            page_rect = getattr(page, "rect", None)
            page_height = float(page_rect.height) if page_rect is not None else None
            copied_tables = [
                copied
                for table_index, table in enumerate(found_tables)
                if (copied := _copy_table(table, page_number, table_index, strategy, page_height)) is not None
            ]
        except Exception:
            continue
        if copied_tables:
            table_count = len(copied_tables)
            for table_index, copied_table in enumerate(copied_tables):
                copied_table["table_index"] = table_index
                copied_table["table_count"] = table_count
            return copied_tables
    return []


def read_pdf_pages(pdf_path: str | Path) -> list[dict]:
    path = Path(pdf_path)
    pages: list[dict] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            pages.append(
                {
                    "page": index,
                    "text": clean_text(page.get_text("text")),
                    "tables": _extract_page_tables(page, index),
                }
            )
    return pages
