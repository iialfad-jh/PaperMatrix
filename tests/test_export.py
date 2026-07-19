from pathlib import Path

from papermatrix.export import export_evidence, export_markdown
from papermatrix.schema import Evidence, ExtractedField, FieldSpec, PaperExtract


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
    export_markdown([extract], output, language="en")

    text = output.read_text(encoding="utf-8")
    assert "A \\| B" in text
    assert "problem \\| value [p.1]" in text


def test_markdown_export_defaults_to_chinese(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        problem=ExtractedField(value="提出矩阵抽取问题", evidence=[Evidence(chunk_id="paper1_c0", pages=[1, 2])]),
        method=ExtractedField(value="unknown"),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )

    output = tmp_path / "matrix.md"
    export_markdown([extract], output)

    text = output.read_text(encoding="utf-8")
    assert "| 论文 | 研究问题 | 方法 | 数据集 | 评价指标 | 结果 | 局限 |" in text
    assert "提出矩阵抽取问题 [第1页, 第2页]" in text
    assert "未知" in text


def test_markdown_export_supports_custom_fields(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        fields={
            "input": ExtractedField(value="early images", evidence=[Evidence(chunk_id="paper1_c0", pages=[1])]),
            "output": ExtractedField(value="future canopy image", evidence=[Evidence(chunk_id="paper1_c1", pages=[2])]),
        },
    )

    output = tmp_path / "matrix.md"
    export_markdown([extract], output, language="en", field_names=["input", "output"])

    text = output.read_text(encoding="utf-8")
    assert "| Paper | Input | Output |" in text
    assert "early images [p.1]" in text
    assert "future canopy image [p.2]" in text


def test_markdown_export_uses_configured_field_labels(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        fields={
            "crop_species": ExtractedField(value="maize", evidence=[Evidence(chunk_id="paper1_c0", pages=[1])]),
        },
    )

    output = tmp_path / "matrix.md"
    export_markdown(
        [extract],
        output,
        language="en",
        field_specs=[FieldSpec(name="crop_species", label_en="Crop/Species")],
    )

    text = output.read_text(encoding="utf-8")
    assert "| Paper | Crop/Species |" in text
    assert "maize [p.1]" in text


def test_evidence_export_includes_chunk_excerpt(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        problem=ExtractedField(value="problem value", evidence=[Evidence(chunk_id="paper1_c0", pages=[1])]),
        method=ExtractedField(value="unknown"),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )
    chunks_by_paper = {
        "paper1": [
            {
                "chunk_id": "paper1_c0",
                "paper_id": "paper1",
                "pages": [1],
                "text": "This source sentence supports the extracted problem value.",
            }
        ]
    }

    output = tmp_path / "matrix.evidence.md"
    export_evidence([extract], output, chunks_by_paper=chunks_by_paper, language="en")

    text = output.read_text(encoding="utf-8")
    assert "# Evidence" in text
    assert "## Paper One" in text
    assert "### Problem" in text
    assert "**Value:** problem value" in text
    assert "- **chunk:** `paper1_c0`; **pages:** p.1" in text
    assert "> This source sentence supports the extracted problem value." in text


def test_evidence_export_selects_relevant_sentences(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        problem=ExtractedField(value="unknown"),
        method=ExtractedField(value="conditional GAN framework", evidence=[Evidence(chunk_id="paper1_c0", pages=[2])]),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )
    chunks_by_paper = {
        "paper1": [
            {
                "chunk_id": "paper1_c0",
                "paper_id": "paper1",
                "pages": [2],
                "text": (
                    "Plant growth is difficult to observe at scale. "
                    "We propose a conditional GAN framework for future image prediction. "
                    "The model takes early images and treatment conditions as input. "
                    "The appendix lists unrelated camera settings."
                ),
            }
        ]
    }

    output = tmp_path / "matrix.evidence.md"
    export_evidence([extract], output, chunks_by_paper=chunks_by_paper, language="en")

    text = output.read_text(encoding="utf-8")
    assert "> Plant growth is difficult to observe at scale." not in text
    assert "> We propose a conditional GAN framework for future image prediction." in text
    assert "> The model takes early images and treatment conditions as input." in text


def test_evidence_export_marks_missing_chunk_text(tmp_path: Path):
    extract = PaperExtract(
        paper_id="paper1",
        title="Paper One",
        problem=ExtractedField(value="problem value", evidence=[Evidence(chunk_id="paper1_c0", pages=[1])]),
        method=ExtractedField(value="unknown"),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )

    output = tmp_path / "matrix.evidence.md"
    export_evidence([extract], output, chunks_by_paper={}, language="en")

    text = output.read_text(encoding="utf-8")
    assert "- **chunk:** `paper1_c0`; **pages:** p.1" in text
    assert "> Chunk text unavailable." in text
