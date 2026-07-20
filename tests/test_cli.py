from pathlib import Path

from typer.testing import CliRunner

from papermatrix import cli
from papermatrix.cache import build_cache_metadata, load_cache_metadata, save_cache_metadata
from papermatrix.extract import save_extract_json
from papermatrix.llm import resolve_openai_config
from papermatrix.schema import Evidence, ExtractedField, PaperExtract, field_specs_from_names, field_specs_metadata


runner = CliRunner()


def make_extract(title: str, problem: str) -> PaperExtract:
    return PaperExtract(
        paper_id="paper",
        title=title,
        problem=ExtractedField(value=problem, evidence=[Evidence(chunk_id="paper_c0", pages=[1])]),
        method=ExtractedField(value="unknown"),
        dataset=ExtractedField(value="unknown"),
        metric=ExtractedField(value="unknown"),
        result=ExtractedField(value="unknown"),
        limitation=ExtractedField(value="unknown"),
    )


def save_matching_metadata(
    pdf_path: Path,
    out: Path,
    language: str = "en",
    field_names: list[str] | None = None,
) -> None:
    field_names = field_names or ["problem", "method", "dataset", "metric", "result", "limitation"]
    field_specs = field_specs_from_names(field_names)
    save_cache_metadata(
        build_cache_metadata(
            pdf_path,
            language=language,
            llm_config=resolve_openai_config(language=language),
            max_chars=3500,
            max_chunks=12,
            fields_metadata=field_specs_metadata(field_specs),
        ),
        out.parent / ".papermatrix" / f"{pdf_path.stem}_meta.json",
    )


def test_cli_reuses_cached_extract_without_reading_pdf_or_llm(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    save_extract_json(make_extract("Cached Title", "cached problem"), tmp_path / ".papermatrix" / "paper_extract.json")
    save_matching_metadata(pdf_path, out, language="en")

    def fail_openai_client(*_args, **_kwargs):
        raise AssertionError("OpenAILLMClient should not be initialized when cache is available")

    def fail_read_pdf_pages(_path):
        raise AssertionError("read_pdf_pages should not be called when cache is available")

    monkeypatch.setattr(cli, "OpenAILLMClient", fail_openai_client)
    monkeypatch.setattr(cli, "read_pdf_pages", fail_read_pdf_pages)

    result = runner.invoke(cli.app, [str(papers_dir), "--out", str(out), "--language", "en"])

    assert result.exit_code == 0, result.output
    assert "Using cached extract for paper.pdf" in result.output
    text = out.read_text(encoding="utf-8")
    assert "Cached Title" in text
    assert "cached problem [p.1]" in text
    evidence_text = out.with_suffix(".evidence.md").read_text(encoding="utf-8")
    assert "Cached Title" in evidence_text
    assert "> Chunk text unavailable." in evidence_text


def test_cli_reruns_when_cache_metadata_differs(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    save_extract_json(make_extract("Cached Title", "cached problem"), tmp_path / ".papermatrix" / "paper_extract.json")
    save_matching_metadata(pdf_path, out, language="zh")
    calls = []

    class FakeOpenAILLMClient:
        def __init__(self, **_kwargs):
            calls.append("llm")

    def fake_read_pdf_pages(_path):
        calls.append("pdf")
        return [{"page": 1, "text": "This paper proposes a metadata-aware cache."}]

    def fake_extract_paper(paper_id, selected_chunks, llm_client, field_names=None, field_specs=None):
        calls.append(("extract", paper_id, selected_chunks, llm_client.__class__.__name__, field_names))
        return make_extract("Fresh Title", "fresh problem")

    monkeypatch.setattr(cli, "OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(cli, "read_pdf_pages", fake_read_pdf_pages)
    monkeypatch.setattr(cli, "extract_paper", fake_extract_paper)

    result = runner.invoke(cli.app, [str(papers_dir), "--out", str(out), "--language", "en"])

    assert result.exit_code == 0, result.output
    assert "Cache metadata changed; rerunning paper.pdf..." in result.output
    assert calls[0:2] == ["pdf", "llm"]
    text = out.read_text(encoding="utf-8")
    assert "Fresh Title" in text
    assert "Cached Title" not in text
    metadata = load_cache_metadata(tmp_path / ".papermatrix" / "paper_meta.json")
    assert metadata["language"] == "en"


def test_cli_uses_custom_fields(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    calls = []

    class FakeOpenAILLMClient:
        def __init__(self, **_kwargs):
            calls.append("llm")

    def fake_read_pdf_pages(_path):
        calls.append("pdf")
        return [{"page": 1, "text": "The input uses early images and the output is a future canopy image."}]

    def fake_extract_paper(paper_id, selected_chunks, llm_client, field_names=None, field_specs=None):
        calls.append(("extract", field_names, [field_spec.name for field_spec in field_specs]))
        return PaperExtract(
            paper_id=paper_id,
            title="Custom Paper",
            fields={
                "input": ExtractedField(value="early images", evidence=[Evidence(chunk_id="paper_c0", pages=[1])]),
                "output": ExtractedField(value="future canopy image", evidence=[Evidence(chunk_id="paper_c0", pages=[1])]),
            },
        )

    monkeypatch.setattr(cli, "OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(cli, "read_pdf_pages", fake_read_pdf_pages)
    monkeypatch.setattr(cli, "extract_paper", fake_extract_paper)

    result = runner.invoke(cli.app, [str(papers_dir), "--out", str(out), "--language", "en", "--fields", "input,output"])

    assert result.exit_code == 0, result.output
    assert calls[2] == ("extract", ["input", "output"], ["input", "output"])
    text = out.read_text(encoding="utf-8")
    assert "| Paper | Input | Output |" in text
    assert "early images [p.1]" in text
    metadata = load_cache_metadata(tmp_path / ".papermatrix" / "paper_meta.json")
    assert [field["name"] for field in metadata["fields"]] == ["input", "output"]


def test_cli_uses_fields_config_file(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    fields_path = tmp_path / "fields.json"
    fields_path.write_text(
        """{
  "fields": [
    {
      "name": "crop_species",
      "label_en": "Crop/Species",
      "label_zh": "作物/物种",
      "description": "Extract the crop or plant species studied in the paper.",
      "keywords": ["crop", "species", "maize"]
    }
  ]
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "matrix.md"
    calls = []

    class FakeOpenAILLMClient:
        def __init__(self, **_kwargs):
            calls.append("llm")

    def fake_read_pdf_pages(_path):
        calls.append("pdf")
        return [{"page": 1, "text": "The crop species is maize."}]

    def fake_extract_paper(paper_id, selected_chunks, llm_client, field_names=None, field_specs=None):
        calls.append(("extract", field_specs[0].label_en, field_specs[0].description, field_specs[0].keywords))
        return PaperExtract(
            paper_id=paper_id,
            title="Config Paper",
            fields={
                "crop_species": ExtractedField(value="maize", evidence=[Evidence(chunk_id="paper_c0", pages=[1])]),
            },
        )

    monkeypatch.setattr(cli, "OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(cli, "read_pdf_pages", fake_read_pdf_pages)
    monkeypatch.setattr(cli, "extract_paper", fake_extract_paper)

    result = runner.invoke(cli.app, [str(papers_dir), "--out", str(out), "--language", "en", "--fields", str(fields_path)])

    assert result.exit_code == 0, result.output
    assert calls[2] == (
        "extract",
        "Crop/Species",
        "Extract the crop or plant species studied in the paper.",
        ["crop", "species", "maize"],
    )
    text = out.read_text(encoding="utf-8")
    assert "| Paper | Crop/Species |" in text
    assert "maize [p.1]" in text


def test_cli_force_ignores_cached_extract(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    save_extract_json(make_extract("Cached Title", "cached problem"), tmp_path / ".papermatrix" / "paper_extract.json")
    calls = []

    class FakeOpenAILLMClient:
        def __init__(self, **_kwargs):
            calls.append("llm")

    def fake_read_pdf_pages(_path):
        calls.append("pdf")
        return [{"page": 1, "text": "This paper proposes a cached-rerun method."}]

    def fake_extract_paper(paper_id, selected_chunks, llm_client, field_names=None, field_specs=None):
        calls.append(("extract", paper_id, selected_chunks, llm_client.__class__.__name__, field_names))
        return make_extract("Fresh Title", "fresh problem")

    monkeypatch.setattr(cli, "OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(cli, "read_pdf_pages", fake_read_pdf_pages)
    monkeypatch.setattr(cli, "extract_paper", fake_extract_paper)

    result = runner.invoke(cli.app, [str(papers_dir), "--out", str(out), "--language", "en", "--force"])

    assert result.exit_code == 0, result.output
    assert "Using cached extract" not in result.output
    assert calls[0:2] == ["pdf", "llm"]
    assert calls[2][0] == "extract"
    text = out.read_text(encoding="utf-8")
    assert "Fresh Title" in text
    assert "Cached Title" not in text
    evidence_text = out.with_suffix(".evidence.md").read_text(encoding="utf-8")
    assert "Fresh Title" in evidence_text
    assert "> This paper proposes a cached-rerun method." in evidence_text
    assert load_cache_metadata(tmp_path / ".papermatrix" / "paper_meta.json") is not None


def test_cli_resolves_remote_source_into_download_cache(tmp_path: Path, monkeypatch):
    downloaded_pdf = tmp_path / ".papermatrix" / "downloads" / "arxiv-2401.12345.pdf"
    downloaded_pdf.parent.mkdir(parents=True)
    downloaded_pdf.write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    calls = []

    def fake_resolve_pdf_paths(source, download_dir, force=False):
        calls.append((source, download_dir, force))
        return [downloaded_pdf]

    class FakeOpenAILLMClient:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr(cli, "resolve_pdf_paths", fake_resolve_pdf_paths)
    monkeypatch.setattr(cli, "OpenAILLMClient", FakeOpenAILLMClient)
    monkeypatch.setattr(cli, "read_pdf_pages", lambda _path: [{"page": 1, "text": "A remote paper."}])
    monkeypatch.setattr(
        cli,
        "extract_paper",
        lambda paper_id, *_args, **_kwargs: make_extract("Remote Paper", "remote problem"),
    )

    result = runner.invoke(cli.app, ["arxiv:2401.12345", "--out", str(out), "--language", "en"])

    assert result.exit_code == 0, result.output
    assert calls == [("arxiv:2401.12345", tmp_path / ".papermatrix" / "downloads", False)]
    assert "Remote Paper" in out.read_text(encoding="utf-8")
