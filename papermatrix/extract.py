from __future__ import annotations

import json
from pathlib import Path

from .llm import LLMClient
from .schema import DEFAULT_FIELD_NAMES, PaperExtract, unknown_field


def validate_extract(raw_extract: dict, paper_id: str, field_names: list[str] | None = None) -> PaperExtract:
    field_names = field_names or list(DEFAULT_FIELD_NAMES)
    raw_extract = dict(raw_extract)
    raw_fields = raw_extract.get("fields") if isinstance(raw_extract.get("fields"), dict) else {}
    fields = {}
    for field_name in field_names:
        fields[field_name] = raw_fields.get(field_name) or raw_extract.get(field_name) or unknown_field().model_dump()

    extract = PaperExtract.model_validate(
        {
            "paper_id": raw_extract.get("paper_id") or paper_id,
            "title": raw_extract.get("title") or paper_id,
            "fields": fields,
        }
    )

    for field_name in field_names:
        field = extract.fields[field_name]
        if field.value != "unknown" and not field.evidence:
            field.value = "unknown"

    return extract


def extract_paper(
    paper_id: str,
    selected_chunks: list[dict],
    llm_client: LLMClient,
    field_names: list[str] | None = None,
) -> PaperExtract:
    raw_extract = llm_client.extract_json(paper_id=paper_id, chunks=selected_chunks, field_names=field_names)
    return validate_extract(raw_extract, paper_id=paper_id, field_names=field_names)


def load_extract_json(path: str | Path, paper_id: str, field_names: list[str] | None = None) -> PaperExtract:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as file:
        raw_extract = json.load(file)
    return validate_extract(raw_extract, paper_id=paper_id, field_names=field_names)


def save_extract_json(extract: PaperExtract, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(extract.model_dump(), file, ensure_ascii=False, indent=2)
