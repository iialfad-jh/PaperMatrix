import pytest

from papermatrix.presets import list_presets, load_preset


def test_lists_builtin_presets():
    assert [preset.name for preset in list_presets()] == [
        "general",
        "machine-learning",
        "plant-growth",
        "survey",
    ]


def test_loads_plant_growth_preset_fields():
    preset = load_preset("Plant-Growth")

    assert preset.name == "plant-growth"
    assert [field.name for field in preset.fields] == [
        "crop_species",
        "growth_stage",
        "treatment",
        "environment",
        "model_input",
        "model_output",
        "dataset",
        "metric",
        "result",
    ]
    assert preset.fields[0].label_zh == "作物/物种"
    assert "species" in preset.fields[0].keywords


def test_rejects_unknown_preset():
    with pytest.raises(ValueError, match='unknown preset "medical"'):
        load_preset("medical")
