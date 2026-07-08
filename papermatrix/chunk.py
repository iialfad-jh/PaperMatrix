from __future__ import annotations

import json
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


def chunk_pages(pages: list[dict], paper_id: str, max_chars: int = 3500) -> list[dict]:
    chunks: list[dict] = []
    current_text: list[str] = []
    current_pages: list[int] = []

    def flush() -> None:
        if not current_text:
            return
        chunk_index = len(chunks)
        chunks.append(
            {
                "chunk_id": f"{paper_id}_c{chunk_index}",
                "paper_id": paper_id,
                "pages": sorted(set(current_pages)),
                "text": " ".join(current_text).strip(),
            }
        )
        current_text.clear()
        current_pages.clear()

    for page in pages:
        page_number = int(page["page"])
        text = str(page.get("text", "")).strip()
        if not text:
            continue

        for part in _split_long_text(text, max_chars):
            current_len = sum(len(item) for item in current_text) + max(0, len(current_text) - 1)
            if current_text and current_len + 1 + len(part) > max_chars:
                flush()
            current_text.append(part)
            current_pages.append(page_number)
            if len(part) >= max_chars:
                flush()

    flush()
    return chunks


def save_chunks_jsonl(chunks: list[dict], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
