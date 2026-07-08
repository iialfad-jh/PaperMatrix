from pydantic import BaseModel, Field


class Evidence(BaseModel):
    chunk_id: str
    pages: list[int]


class ExtractedField(BaseModel):
    value: str
    evidence: list[Evidence] = Field(default_factory=list)


class PaperExtract(BaseModel):
    paper_id: str
    title: str
    problem: ExtractedField
    method: ExtractedField
    dataset: ExtractedField
    metric: ExtractedField
    result: ExtractedField
    limitation: ExtractedField


EXTRACTED_FIELD_NAMES = (
    "problem",
    "method",
    "dataset",
    "metric",
    "result",
    "limitation",
)


def unknown_field() -> ExtractedField:
    return ExtractedField(value="unknown", evidence=[])
