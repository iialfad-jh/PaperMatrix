from __future__ import annotations

import json
from pathlib import Path


CACHE_VERSION = 2


def build_cache_metadata(
    pdf_path: str | Path,
    *,
    language: str,
    llm_config: dict[str, str],
    max_chars: int,
    max_chunks: int,
    fields_metadata: list[dict] | None = None,
    field_names: list[str] | None = None,
    preset: str | None = None,
    paper_id: str | None = None,
) -> dict:
    path = Path(pdf_path)
    stat = path.stat()
    return {
        "cache_version": CACHE_VERSION,
        "paper_id": paper_id or path.stem,
        "pdf": {
            "name": path.name,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "language": language,
        "llm": {
            "model": llm_config["model"],
            "api_mode": llm_config["api_mode"],
            "base_url": llm_config["base_url"],
        },
        "chunking": {
            "max_chars": max_chars,
            "max_chunks": max_chunks,
        },
        "fields": fields_metadata if fields_metadata is not None else field_names,
        "preset": preset,
    }


def load_cache_metadata(path: str | Path) -> dict | None:
    input_path = Path(path)
    if not input_path.exists():
        return None
    try:
        with input_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return metadata if isinstance(metadata, dict) else None


def save_cache_metadata(metadata: dict, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)


def is_cache_metadata_current(cached_metadata: dict | None, current_metadata: dict) -> bool:
    return cached_metadata == current_metadata
