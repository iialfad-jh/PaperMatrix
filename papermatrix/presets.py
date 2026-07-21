from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .schema import FieldSpec, load_field_specs


PRESETS_DIR = Path(__file__).with_name("presets")
PRESET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class FieldPreset:
    name: str
    description_en: str
    description_zh: str
    fields: list[FieldSpec]

    def description(self, language: str) -> str:
        return self.description_zh if language == "zh" else self.description_en

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description_zh": self.description_zh,
            "description_en": self.description_en,
            "fields": [field.model_dump() for field in self.fields],
        }


def list_presets() -> list[FieldPreset]:
    return [load_preset(path.stem) for path in sorted(PRESETS_DIR.glob("*.json"))]


def load_preset(name: str) -> FieldPreset:
    normalized_name = name.strip().lower()
    if not PRESET_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError(f'invalid preset name "{name}"')

    path = PRESETS_DIR / f"{normalized_name}.json"
    if not path.exists():
        available = ", ".join(preset_path.stem for preset_path in sorted(PRESETS_DIR.glob("*.json")))
        raise ValueError(f'unknown preset "{name}"; available presets: {available}')

    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load preset: {normalized_name}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"preset must contain a JSON object: {normalized_name}")

    return FieldPreset(
        name=normalized_name,
        description_en=str(raw.get("description_en", "")),
        description_zh=str(raw.get("description_zh", "")),
        fields=load_field_specs(path),
    )
