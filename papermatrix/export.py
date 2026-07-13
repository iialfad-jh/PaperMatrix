from __future__ import annotations

import csv
import re
from pathlib import Path

from .schema import ExtractedField, PaperExtract


FIELD_ORDER = ["problem", "method", "dataset", "metric", "result", "limitation"]
LANGUAGE_ALIASES = {
    "zh": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
}
MATRIX_COLUMNS = {
    "en": ["Paper", "Problem", "Method", "Dataset", "Metric", "Result", "Limitation"],
    "zh": ["论文", "研究问题", "方法", "数据集", "评价指标", "结果", "局限"],
}
UNKNOWN_LABELS = {
    "en": "unknown",
    "zh": "未知",
}
PAGE_PREFIXES = {
    "en": "p.",
    "zh": "第",
}
PAGE_SUFFIXES = {
    "en": "",
    "zh": "页",
}
EVIDENCE_LABELS = {
    "en": {
        "title": "Evidence",
        "value": "Value",
        "evidence": "Evidence",
        "chunk": "chunk",
        "pages": "pages",
        "excerpt": "Excerpt",
        "missing_excerpt": "Chunk text unavailable.",
    },
    "zh": {
        "title": "证据",
        "value": "抽取值",
        "evidence": "证据",
        "chunk": "片段",
        "pages": "页码",
        "excerpt": "原文摘录",
        "missing_excerpt": "无法找到片段原文。",
    },
}


def normalize_language(language: str) -> str:
    normalized = LANGUAGE_ALIASES.get(language.strip().lower())
    if not normalized:
        raise ValueError('language must be "zh" or "en"')
    return normalized


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def format_field(field: ExtractedField, language: str = "zh") -> str:
    language = normalize_language(language)
    if field.value == "unknown":
        return UNKNOWN_LABELS[language]
    if not field.evidence:
        return field.value
    pages = sorted({page for evidence in field.evidence for page in evidence.pages})
    if not pages:
        return field.value
    page_text = ", ".join(f"{PAGE_PREFIXES[language]}{page}{PAGE_SUFFIXES[language]}" for page in pages)
    return f"{field.value} [{page_text}]"


def _format_pages(pages: list[int], language: str) -> str:
    if not pages:
        return UNKNOWN_LABELS[language]
    return ", ".join(f"{PAGE_PREFIXES[language]}{page}{PAGE_SUFFIXES[language]}" for page in sorted(set(pages)))


def _short_excerpt(text: str, max_chars: int) -> str:
    excerpt = re.sub(r"\s+", " ", text).strip()
    if len(excerpt) <= max_chars:
        return excerpt
    split_at = excerpt.rfind(" ", 0, max_chars)
    if split_at < max_chars // 2:
        split_at = max_chars
    return excerpt[:split_at].rstrip() + "..."


def _quote_markdown(text: str) -> list[str]:
    if not text:
        return []
    return [f"> {line}" for line in text.splitlines()]


def extract_to_row(extract: PaperExtract, language: str = "zh") -> dict[str, str]:
    language = normalize_language(language)
    columns = MATRIX_COLUMNS[language]
    row = {columns[0]: extract.title or extract.paper_id}
    for column, field_name in zip(columns[1:], FIELD_ORDER):
        row[column] = format_field(getattr(extract, field_name), language=language)
    return row


def export_markdown(extracts: list[PaperExtract], path: str | Path, language: str = "zh") -> None:
    language = normalize_language(language)
    columns = MATRIX_COLUMNS[language]
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [extract_to_row(extract, language=language) for extract in extracts]

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_markdown_cell(row[column]) for column in columns) + " |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(extracts: list[PaperExtract], path: str | Path, language: str = "zh") -> None:
    language = normalize_language(language)
    columns = MATRIX_COLUMNS[language]
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [extract_to_row(extract, language=language) for extract in extracts]
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def export_evidence(
    extracts: list[PaperExtract],
    path: str | Path,
    chunks_by_paper: dict[str, list[dict]] | None = None,
    language: str = "zh",
    excerpt_chars: int = 700,
) -> None:
    language = normalize_language(language)
    labels = EVIDENCE_LABELS[language]
    columns = MATRIX_COLUMNS[language]
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_indexes = {
        paper_id: {str(chunk.get("chunk_id")): chunk for chunk in chunks}
        for paper_id, chunks in (chunks_by_paper or {}).items()
    }

    lines = [f"# {labels['title']}", ""]
    for extract in extracts:
        lines.extend([f"## {extract.title or extract.paper_id}", ""])
        chunk_index = chunk_indexes.get(extract.paper_id, {})
        for field_name, field_label in zip(FIELD_ORDER, columns[1:]):
            field = getattr(extract, field_name)
            if field.value == "unknown" and not field.evidence:
                continue

            lines.extend([f"### {field_label}", "", f"**{labels['value']}:** {field.value}", ""])
            if not field.evidence:
                continue

            lines.extend([f"**{labels['evidence']}:**", ""])
            for evidence in field.evidence:
                lines.append(
                    f"- **{labels['chunk']}:** `{evidence.chunk_id}`; "
                    f"**{labels['pages']}:** {_format_pages(evidence.pages, language)}"
                )
                chunk = chunk_index.get(evidence.chunk_id)
                excerpt = _short_excerpt(str(chunk.get("text", "")), excerpt_chars) if chunk else ""
                lines.extend(["", f"{labels['excerpt']}:", ""])
                if excerpt:
                    lines.extend(_quote_markdown(excerpt))
                else:
                    lines.append(f"> {labels['missing_excerpt']}")
                lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def export_matrix(extracts: list[PaperExtract], markdown_path: str | Path, language: str = "zh") -> tuple[Path, Path]:
    md_path = Path(markdown_path)
    csv_path = md_path.with_suffix(".csv")
    export_markdown(extracts, md_path, language=language)
    export_csv(extracts, csv_path, language=language)
    return md_path, csv_path
