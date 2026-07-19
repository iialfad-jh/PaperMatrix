from __future__ import annotations

import csv
import re
from pathlib import Path

from .schema import DEFAULT_FIELD_NAMES, ExtractedField, FieldSpec, PaperExtract, field_label, field_specs_from_names


FIELD_ORDER = list(DEFAULT_FIELD_NAMES)
LANGUAGE_ALIASES = {
    "zh": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
}
MATRIX_COLUMNS = {
    "en": ["Paper"] + [field_label(field_name, "en") for field_name in FIELD_ORDER],
    "zh": ["论文"] + [field_label(field_name, "zh") for field_name in FIELD_ORDER],
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
EVIDENCE_KEYWORDS = {
    "problem": ["problem", "challenge", "task", "aim", "goal", "motivation", "need", "address"],
    "method": ["method", "approach", "framework", "architecture", "model", "propose", "introduce", "algorithm", "train"],
    "dataset": ["dataset", "datasets", "benchmark", "corpus", "data", "images", "samples", "collected"],
    "metric": ["metric", "metrics", "accuracy", "f1", "precision", "recall", "auc", "score", "fid", "mae", "r2"],
    "result": ["result", "results", "outperform", "improve", "achieve", "performance", "significant", "better", "lower", "higher"],
    "limitation": ["limitation", "limitations", "future work", "fail", "failure", "weakness", "cannot", "does not", "challenge"],
}
VALUE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "using",
    "used",
    "based",
    "paper",
    "method",
    "model",
    "result",
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


def _resolve_field_specs(
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> list[FieldSpec]:
    return field_specs or field_specs_from_names(field_names or list(DEFAULT_FIELD_NAMES))


def matrix_columns(
    field_names: list[str] | None = None,
    language: str = "zh",
    field_specs: list[FieldSpec] | None = None,
) -> list[str]:
    language = normalize_language(language)
    field_specs = _resolve_field_specs(field_names=field_names, field_specs=field_specs)
    paper_column = "Paper" if language == "en" else "论文"
    return [paper_column] + [field_label(field_spec.name, language, field_specs=field_specs) for field_spec in field_specs]


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


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?。！？])\s+", normalized) if sentence.strip()]


def _value_terms(value: str) -> list[str]:
    terms = []
    seen = set()
    for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}|\d+(?:\.\d+)?", value.lower()):
        if term in VALUE_STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms[:20]


def _sentence_score(
    sentence: str,
    field_name: str,
    field_value: str,
    field_spec: FieldSpec | None = None,
) -> float:
    text = sentence.lower()
    score = 0.0
    keywords = []
    keywords.extend(EVIDENCE_KEYWORDS.get(field_name, []))
    if field_spec:
        keywords.extend(field_spec.keywords)
    keywords.extend(_value_terms(field_name))
    for keyword in keywords:
        matches = re.findall(re.escape(keyword), text)
        if matches:
            score += 2.0 + min(len(matches), 3)
    for term in _value_terms(field_value):
        if term in text:
            score += 1.5
    if field_name in {"metric", "result"} and re.search(r"\d", sentence):
        score += 1.5
    if field_name == "result" and re.search(r"\b(?:better|higher|lower|improv\w*|outperform\w*|achiev\w*)\b", text):
        score += 1.5
    if len(sentence) < 25:
        score -= 0.5
    return score


def _evidence_excerpt(
    text: str,
    field_name: str,
    field_value: str,
    max_chars: int,
    max_sentences: int = 3,
    field_spec: FieldSpec | None = None,
) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""

    scored = [
        (_sentence_score(sentence, field_name, field_value, field_spec=field_spec), index, sentence)
        for index, sentence in enumerate(sentences)
    ]
    selected = sorted(
        [item for item in sorted(scored, key=lambda item: (item[0], -item[1]), reverse=True)[:max_sentences] if item[0] > 0],
        key=lambda item: item[1],
    )
    if not selected:
        return _short_excerpt(text, max_chars)

    excerpt_lines = []
    current_chars = 0
    for _score, _index, sentence in selected:
        next_len = len(sentence) + (1 if excerpt_lines else 0)
        if excerpt_lines and current_chars + next_len > max_chars:
            break
        if not excerpt_lines and len(sentence) > max_chars:
            return _short_excerpt(sentence, max_chars)
        excerpt_lines.append(sentence)
        current_chars += next_len
    return "\n".join(excerpt_lines)


def _quote_markdown(text: str) -> list[str]:
    if not text:
        return []
    return [f"> {line}" for line in text.splitlines()]


def extract_to_row(
    extract: PaperExtract,
    language: str = "zh",
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> dict[str, str]:
    language = normalize_language(language)
    field_specs = _resolve_field_specs(field_names=field_names, field_specs=field_specs)
    field_names = [field_spec.name for field_spec in field_specs]
    columns = matrix_columns(field_names=field_names, language=language, field_specs=field_specs)
    row = {columns[0]: extract.title or extract.paper_id}
    for column, field_name in zip(columns[1:], field_names):
        row[column] = format_field(extract.get_field(field_name), language=language)
    return row


def export_markdown(
    extracts: list[PaperExtract],
    path: str | Path,
    language: str = "zh",
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> None:
    language = normalize_language(language)
    field_specs = _resolve_field_specs(field_names=field_names, field_specs=field_specs)
    field_names = [field_spec.name for field_spec in field_specs]
    columns = matrix_columns(field_names=field_names, language=language, field_specs=field_specs)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        extract_to_row(extract, language=language, field_names=field_names, field_specs=field_specs)
        for extract in extracts
    ]

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_markdown_cell(row[column]) for column in columns) + " |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(
    extracts: list[PaperExtract],
    path: str | Path,
    language: str = "zh",
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> None:
    language = normalize_language(language)
    field_specs = _resolve_field_specs(field_names=field_names, field_specs=field_specs)
    field_names = [field_spec.name for field_spec in field_specs]
    columns = matrix_columns(field_names=field_names, language=language, field_specs=field_specs)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        extract_to_row(extract, language=language, field_names=field_names, field_specs=field_specs)
        for extract in extracts
    ]
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
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> None:
    language = normalize_language(language)
    field_specs = _resolve_field_specs(field_names=field_names, field_specs=field_specs)
    field_names = [field_spec.name for field_spec in field_specs]
    field_specs_by_name = {field_spec.name: field_spec for field_spec in field_specs}
    labels = EVIDENCE_LABELS[language]
    columns = matrix_columns(field_names=field_names, language=language, field_specs=field_specs)
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
        for field_name, column_label in zip(field_names, columns[1:]):
            field = extract.get_field(field_name)
            if field.value == "unknown" and not field.evidence:
                continue

            lines.extend([f"### {column_label}", "", f"**{labels['value']}:** {field.value}", ""])
            if not field.evidence:
                continue

            lines.extend([f"**{labels['evidence']}:**", ""])
            for evidence in field.evidence:
                lines.append(
                    f"- **{labels['chunk']}:** `{evidence.chunk_id}`; "
                    f"**{labels['pages']}:** {_format_pages(evidence.pages, language)}"
                )
                chunk = chunk_index.get(evidence.chunk_id)
                excerpt = (
                    _evidence_excerpt(
                        str(chunk.get("text", "")),
                        field_name,
                        field.value,
                        excerpt_chars,
                        field_spec=field_specs_by_name.get(field_name),
                    )
                    if chunk
                    else ""
                )
                lines.extend(["", f"{labels['excerpt']}:", ""])
                if excerpt:
                    lines.extend(_quote_markdown(excerpt))
                else:
                    lines.append(f"> {labels['missing_excerpt']}")
                lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def export_matrix(
    extracts: list[PaperExtract],
    markdown_path: str | Path,
    language: str = "zh",
    field_names: list[str] | None = None,
    field_specs: list[FieldSpec] | None = None,
) -> tuple[Path, Path]:
    md_path = Path(markdown_path)
    csv_path = md_path.with_suffix(".csv")
    export_markdown(extracts, md_path, language=language, field_names=field_names, field_specs=field_specs)
    export_csv(extracts, csv_path, language=language, field_names=field_names, field_specs=field_specs)
    return md_path, csv_path
