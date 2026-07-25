from __future__ import annotations

import json
import re
from pathlib import Path


def _split_long_text(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _table_signature(header: list[str]) -> tuple[str, ...]:
    return tuple(re.sub(r"\W+", "", cell).lower() for cell in header)


def _collect_tables(pages: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for page in pages:
        page_number = int(page["page"])
        for table in page.get("tables", []):
            header = [str(cell) for cell in table.get("header", [])]
            rows = [[str(cell) for cell in row] for row in table.get("rows", [])]
            if len(header) < 2 or not rows:
                continue
            source = {
                "page": page_number,
                "table_index": int(table.get("table_index", 0)),
                "table_count": int(table.get("table_count", 1)),
                "strategy": str(table.get("strategy", "unknown")),
                "bbox": table.get("bbox"),
            }
            can_merge = False
            if merged:
                previous_source = merged[-1]["sources"][-1]
                can_merge = (
                    page_number == merged[-1]["pages"][-1] + 1
                    and previous_source["table_index"] == previous_source["table_count"] - 1
                    and source["table_index"] == 0
                    and _table_signature(header) == _table_signature(merged[-1]["header"])
                )
            if can_merge:
                merged[-1]["pages"].append(page_number)
                merged[-1]["rows"].extend(rows)
                merged[-1]["sources"].append(source)
            else:
                merged.append({"pages": [page_number], "header": header, "rows": rows, "sources": [source]})
    return merged


def _escape_table_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().replace("|", r"\|")


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(cell) for cell in cells) + " |"


def _table_text(header: list[str], rows: list[list[str]], pages: list[int]) -> str:
    page_label = ", ".join(str(page) for page in pages)
    separator = ["---"] * len(header)
    lines = [f"Table from page(s) {page_label}", _table_row(header), _table_row(separator)]
    lines.extend(_table_row(row) for row in rows)
    return "\n".join(lines)


def _split_table_rows(table: dict, max_chars: int) -> list[list[list[str]]]:
    header = table["header"]
    pages = table["pages"]
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    for row in table["rows"]:
        candidate = current + [row]
        if current and len(_table_text(header, candidate, pages)) > max_chars:
            groups.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups


def chunk_pages(pages: list[dict], paper_id: str, max_chars: int = 3500) -> list[dict]:
    chunks: list[dict] = []
    current_text: list[str] = []
    current_pages: list[int] = []
    table_groups = _collect_tables(pages)
    tables_by_start_page: dict[int, list[dict]] = {}
    for table_group in table_groups:
        tables_by_start_page.setdefault(table_group["pages"][0], []).append(table_group)
    text_index = 0
    table_index = 0

    def flush() -> None:
        nonlocal text_index
        if not current_text:
            return
        chunks.append(
            {
                "chunk_id": f"{paper_id}_c{text_index}",
                "paper_id": paper_id,
                "pages": sorted(set(current_pages)),
                "text": " ".join(current_text).strip(),
            }
        )
        text_index += 1
        current_text.clear()
        current_pages.clear()

    def append_table(table: dict) -> None:
        nonlocal table_index
        table_parts = _split_table_rows(table, max_chars)
        for part_index, rows in enumerate(table_parts, start=1):
            chunk_id = f"{paper_id}_t{table_index}"
            if len(table_parts) > 1:
                chunk_id += f"_{part_index}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "paper_id": paper_id,
                    "pages": table["pages"],
                    "kind": "table",
                    "text": _table_text(table["header"], rows, table["pages"]),
                    "table": {
                        "header": table["header"],
                        "rows": rows,
                        "sources": table["sources"],
                    },
                }
            )
        table_index += 1

    for page in pages:
        page_number = int(page["page"])
        text = str(page.get("text", "")).strip()
        if text:
            for part in _split_long_text(text, max_chars):
                current_len = sum(len(item) for item in current_text) + max(0, len(current_text) - 1)
                if current_text and current_len + 1 + len(part) > max_chars:
                    flush()
                current_text.append(part)
                current_pages.append(page_number)
                if len(part) >= max_chars:
                    flush()

        if page_number in tables_by_start_page:
            flush()
            for table in tables_by_start_page[page_number]:
                append_table(table)

    flush()
    return chunks


def save_chunks_jsonl(chunks: list[dict], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def load_chunks_jsonl(path: str | Path) -> list[dict]:
    input_path = Path(path)
    chunks = []
    with input_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks
