from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


class Evidence(BaseModel):
    chunk_id: str
    pages: list[int]


class ExtractedField(BaseModel):
    value: str
    evidence: list[Evidence] = Field(default_factory=list)


DEFAULT_FIELD_NAMES = (
    "problem",
    "method",
    "dataset",
    "metric",
    "result",
    "limitation",
)
EXTRACTED_FIELD_NAMES = DEFAULT_FIELD_NAMES
FIELD_LABELS = {
    "en": {
        "problem": "Problem",
        "method": "Method",
        "dataset": "Dataset",
        "metric": "Metric",
        "result": "Result",
        "limitation": "Limitation",
    },
    "zh": {
        "problem": "研究问题",
        "method": "方法",
        "dataset": "数据集",
        "metric": "评价指标",
        "result": "结果",
        "limitation": "局限",
    },
}
FIELD_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class FieldSpec(BaseModel):
    name: str
    label_zh: str | None = None
    label_en: str | None = None
    description: str = ""
    keywords: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return normalize_field_name(name)


def normalize_field_name(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_")
    if not FIELD_NAME_PATTERN.match(normalized):
        raise ValueError(f'invalid field name "{name}"; use lowercase letters, numbers, and underscores')
    return normalized


def _check_duplicate_field_names(names: list[str]) -> None:
    seen = set()
    for name in names:
        if name in seen:
            raise ValueError(f'duplicate field name "{name}"')
        seen.add(name)


def parse_field_names(fields: str | None = None) -> list[str]:
    if fields is None or not fields.strip():
        return list(DEFAULT_FIELD_NAMES)

    names = [normalize_field_name(name) for name in fields.split(",") if name.strip()]
    if not names:
        raise ValueError("fields must include at least one field name")
    _check_duplicate_field_names(names)
    return names


def field_specs_from_names(field_names: list[str]) -> list[FieldSpec]:
    return [FieldSpec(name=normalize_field_name(field_name)) for field_name in field_names]


def default_field_specs() -> list[FieldSpec]:
    return field_specs_from_names(list(DEFAULT_FIELD_NAMES))


def _field_spec_from_raw(raw_field: object) -> FieldSpec:
    if isinstance(raw_field, str):
        return FieldSpec(name=normalize_field_name(raw_field))
    if not isinstance(raw_field, dict):
        raise ValueError("each field entry must be a string or object")

    values = dict(raw_field)
    if "name" not in values:
        raise ValueError('field object must include "name"')
    values["name"] = normalize_field_name(str(values["name"]))
    keywords = values.get("keywords", [])
    if isinstance(keywords, str):
        values["keywords"] = [item.strip() for item in keywords.split(",") if item.strip()]
    elif not isinstance(keywords, list):
        raise ValueError(f'field "{values["name"]}" keywords must be a list or comma-separated string')
    return FieldSpec.model_validate(values)


def load_field_specs(path: str | Path) -> list[FieldSpec]:
    input_path = Path(path)
    try:
        with input_path.open("r", encoding="utf-8") as file:
            raw_config = json.load(file)
    except OSError as exc:
        raise ValueError(f"could not read fields file: {input_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid fields JSON: {input_path}") from exc

    raw_fields = raw_config.get("fields") if isinstance(raw_config, dict) else raw_config
    if not isinstance(raw_fields, list):
        raise ValueError('fields file must contain a "fields" list')

    field_specs = [_field_spec_from_raw(raw_field) for raw_field in raw_fields]
    if not field_specs:
        raise ValueError("fields file must include at least one field")
    _check_duplicate_field_names([field.name for field in field_specs])
    return field_specs


def parse_field_specs(fields: str | None = None) -> list[FieldSpec]:
    if fields is None or not fields.strip():
        return default_field_specs()

    fields_text = fields.strip()
    maybe_path = Path(fields_text)
    if "," not in fields_text and (maybe_path.exists() or maybe_path.suffix.lower() == ".json"):
        return load_field_specs(maybe_path)
    return field_specs_from_names(parse_field_names(fields_text))


def field_specs_metadata(field_specs: list[FieldSpec]) -> list[dict]:
    return [field_spec.model_dump() for field_spec in field_specs]


def field_label(field_name: str, language: str = "zh", field_specs: list[FieldSpec] | None = None) -> str:
    if field_specs:
        for field_spec in field_specs:
            if field_spec.name == field_name:
                if language == "en" and field_spec.label_en:
                    return field_spec.label_en
                if language == "zh" and field_spec.label_zh:
                    return field_spec.label_zh
    label = FIELD_LABELS.get(language, {}).get(field_name)
    if label:
        return label
    if language == "en":
        return field_name.replace("_", " ").title()
    return field_name


class PaperExtract(BaseModel):
    paper_id: str
    title: str = ""
    fields: dict[str, ExtractedField] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def collect_legacy_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        raw_fields = values.get("fields") or {}
        fields = dict(raw_fields) if isinstance(raw_fields, dict) else {}
        for field_name in DEFAULT_FIELD_NAMES:
            if field_name in values:
                fields.setdefault(field_name, values.pop(field_name))
        values["fields"] = fields
        return values

    def get_field(self, field_name: str) -> ExtractedField:
        return self.fields.get(field_name, unknown_field())

    @property
    def problem(self) -> ExtractedField:
        return self.get_field("problem")

    @property
    def method(self) -> ExtractedField:
        return self.get_field("method")

    @property
    def dataset(self) -> ExtractedField:
        return self.get_field("dataset")

    @property
    def metric(self) -> ExtractedField:
        return self.get_field("metric")

    @property
    def result(self) -> ExtractedField:
        return self.get_field("result")

    @property
    def limitation(self) -> ExtractedField:
        return self.get_field("limitation")


def unknown_field() -> ExtractedField:
    return ExtractedField(value="unknown", evidence=[])
