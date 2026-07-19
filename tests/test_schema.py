import pytest

from papermatrix.schema import DEFAULT_FIELD_NAMES, FieldSpec, field_label, parse_field_names, parse_field_specs


def test_parse_field_names_defaults_to_builtin_fields():
    assert parse_field_names(None) == list(DEFAULT_FIELD_NAMES)


def test_parse_field_names_normalizes_custom_fields():
    assert parse_field_names("Input, output-field, dataset") == ["input", "output_field", "dataset"]


def test_field_spec_normalizes_name():
    assert FieldSpec(name="Model-Input").name == "model_input"


def test_parse_field_names_rejects_duplicates():
    with pytest.raises(ValueError, match='duplicate field name "input"'):
        parse_field_names("input,input")


def test_field_label_formats_custom_english_columns():
    assert field_label("model_input", language="en") == "Model Input"


def test_parse_field_specs_reads_json_config(tmp_path):
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(
        """{
  "fields": [
    {
      "name": "crop-species",
      "label_zh": "作物/物种",
      "label_en": "Crop/Species",
      "description": "Extract the crop or plant species.",
      "keywords": ["crop", "species"]
    }
  ]
}
""",
        encoding="utf-8",
    )

    field_specs = parse_field_specs(str(fields_path))

    assert field_specs[0].name == "crop_species"
    assert field_specs[0].label_en == "Crop/Species"
    assert field_specs[0].description == "Extract the crop or plant species."
    assert field_specs[0].keywords == ["crop", "species"]


def test_field_label_uses_configured_label():
    field_specs = parse_field_specs("crop_species")
    field_specs[0].label_zh = "作物/物种"

    assert field_label("crop_species", language="zh", field_specs=field_specs) == "作物/物种"
