from pathlib import Path

from papermatrix.export import export_markdown
from papermatrix.schema import Evidence, ExtractedField, PaperExtract


def test_markdown_export_escapes_pipe(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="A | B",
        problem=ExtractedField(value="problem | value", evidence=[Evidence(chunk_id="paper1_c0", pages=[1])]),
        method=ExtractedField(value="unknown"),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )

    output = tmp_path / "matrix.md"
    export_markdown([extract], output)

    text = output.read_text(encoding="utf-8")
    assert "A \\| B" in text
    assert "problem \\| value [p.1]" in text
