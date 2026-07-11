from __future__ import annotations

import json
from pathlib import Path

from .llm import LLMClient
from .schema import EXTRACTED_FIELD_NAMES, PaperExtract


def validate_extract(raw_extract: dict, paper_id: str) -> PaperExtract:
    raw_extract["paper_id"] = raw_extract.get("paper_id") or paper_id
    extract = PaperExtract.model_validate(raw_extract)

    for field_name in EXTRACTED_FIELD_NAMES:
        field = getattr(extract, field_name)
        if field.value != "unknown" and not field.evidence:
            field.value = "unknown"

    return extract


def extract_paper(paper_id: str, selected_chunks: list[dict], llm_client: LLMClient) -> PaperExtract:
    raw_extract = llm_client.extract_json(paper_id=paper_id, chunks=selected_chunks)
    return validate_extract(raw_extract, paper_id=paper_id)


def load_extract_json(path: str | Path, paper_id: str) -> PaperExtract:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as file:
        raw_extract = json.load(file)
    return validate_extract(raw_extract, paper_id=paper_id)


def save_extract_json(extract: PaperExtract, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(extract.model_dump(), file, ensure_ascii=False, indent=2)
