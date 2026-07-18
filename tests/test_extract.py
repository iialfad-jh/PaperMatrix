from papermatrix.extract import validate_extract


def test_validate_extract_accepts_legacy_top_level_fields():
    extract = validate_extract(
        {
            "paper_id": "paper1",
            "title": "Paper One",
            "problem": {"value": "problem value", "evidence": [{"chunk_id": "paper1_c0", "pages": [1]}]},
        },
        paper_id="paper1",
        field_names=["problem", "method"],
    )

    assert extract.problem.value == "problem value"
    assert extract.method.value == "unknown"


def test_validate_extract_accepts_dynamic_fields_object():
    extract = validate_extract(
        {
            "paper_id": "paper1",
            "title": "Paper One",
            "fields": {
                "input": {"value": "early images", "evidence": [{"chunk_id": "paper1_c0", "pages": [1]}]},
                "output": {"value": "future images", "evidence": [{"chunk_id": "paper1_c1", "pages": [2]}]},
            },
        },
        paper_id="paper1",
        field_names=["input", "output"],
    )

    assert extract.get_field("input").value == "early images"
    assert extract.get_field("output").evidence[0].pages == [2]
