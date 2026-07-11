from pathlib import Path

from typer.testing import CliRunner

from papermatrix import cli
from papermatrix.extract import save_extract_json
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


def test_cli_reuses_cached_extract_without_reading_pdf_or_llm(tmp_path: Path, monkeypatch):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    out = tmp_path / "matrix.md"
    save_extract_json(make_extract("Cached Title", "cached problem"), tmp_path / ".papermatrix" / "paper_extract.json")

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
