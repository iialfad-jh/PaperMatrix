import pytest

from papermatrix.schema import DEFAULT_FIELD_NAMES, field_label, parse_field_names


def test_parse_field_names_defaults_to_builtin_fields():
    assert parse_field_names(None) == list(DEFAULT_FIELD_NAMES)


def test_parse_field_names_normalizes_custom_fields():
    assert parse_field_names("Input, output-field, dataset") == ["input", "output_field", "dataset"]


def test_parse_field_names_rejects_duplicates():
    with pytest.raises(ValueError, match='duplicate field name "input"'):
        parse_field_names("input,input")


def test_field_label_formats_custom_english_columns():
    assert field_label("model_input", language="en") == "Model Input"
