from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator


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


def parse_field_names(fields: str | None = None) -> list[str]:
    if fields is None or not fields.strip():
        return list(DEFAULT_FIELD_NAMES)

    names = [name.strip().lower().replace("-", "_") for name in fields.split(",") if name.strip()]
    if not names:
        raise ValueError("fields must include at least one field name")

    seen = set()
    for name in names:
        if not FIELD_NAME_PATTERN.match(name):
            raise ValueError(f'invalid field name "{name}"; use lowercase letters, numbers, and underscores')
        if name in seen:
            raise ValueError(f'duplicate field name "{name}"')
        seen.add(name)
    return names


def field_label(field_name: str, language: str = "zh") -> str:
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
