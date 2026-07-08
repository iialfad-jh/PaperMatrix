from __future__ import annotations

import csv
from pathlib import Path

from .schema import ExtractedField, PaperExtract


MATRIX_COLUMNS = ["Paper", "Problem", "Method", "Dataset", "Metric", "Result", "Limitation"]
FIELD_ORDER = ["problem", "method", "dataset", "metric", "result", "limitation"]


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def format_field(field: ExtractedField) -> str:
    if not field.evidence:
        return field.value
    pages = sorted({page for evidence in field.evidence for page in evidence.pages})
    if not pages:
        return field.value
    page_text = ", ".join(f"p.{page}" for page in pages)
    return f"{field.value} [{page_text}]"


def extract_to_row(extract: PaperExtract) -> dict[str, str]:
    row = {"Paper": extract.title or extract.paper_id}
    for column, field_name in zip(MATRIX_COLUMNS[1:], FIELD_ORDER):
        row[column] = format_field(getattr(extract, field_name))
    return row


def export_markdown(extracts: list[PaperExtract], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [extract_to_row(extract) for extract in extracts]

    lines = [
        "| " + " | ".join(MATRIX_COLUMNS) + " |",
        "| " + " | ".join(["---"] * len(MATRIX_COLUMNS)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_markdown_cell(row[column]) for column in MATRIX_COLUMNS) + " |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(extracts: list[PaperExtract], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [extract_to_row(extract) for extract in extracts]
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=MATRIX_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def export_matrix(extracts: list[PaperExtract], markdown_path: str | Path) -> tuple[Path, Path]:
    md_path = Path(markdown_path)
    csv_path = md_path.with_suffix(".csv")
    export_markdown(extracts, md_path)
    export_csv(extracts, csv_path)
    return md_path, csv_path
