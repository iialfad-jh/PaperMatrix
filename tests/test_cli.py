from pathlib import Path

from typer.testing import CliRunner

from papermatrix import cli
from papermatrix.cache import build_cache_metadata, load_cache_metadata, save_cache_metadata
from papermatrix.extract import save_extract_json
from papermatrix.llm import resolve_openai_config
from papermatrix.schema import Evidence, ExtractedField, PaperExtract


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


def save_matching_metadata(pdf_path: Path, out: Path, language: str = "en") -> None:
    save_cache_metadata(
        build_cache_metadata(
            pdf_path,
            language=language,
            llm_config=resolve_openai_config(language=language),
            max_chars=3500,
            max_chunks=12,
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

    def fake_extract_paper(paper_id, selected_chunks, llm_client):
        calls.append(("extract", paper_id, selected_chunks, llm_client.__class__.__name__))
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

    def fake_extract_paper(paper_id, selected_chunks, llm_client):
        calls.append(("extract", paper_id, selected_chunks, llm_client.__class__.__name__))
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
