from pathlib import Path

from papermatrix import batch


def test_load_sources_file_ignores_comments_and_resolves_relative_paths(tmp_path: Path):
    local_pdf = tmp_path / "papers" / "local.pdf"
    local_pdf.parent.mkdir()
    local_pdf.write_bytes(b"%PDF-")
    sources_file = tmp_path / "sources.txt"
    sources_file.write_text(
        "\ufeff# Papers\n\npapers/local.pdf\narxiv:2401.12345\n",
        encoding="utf-8",
    )

    entries = batch.load_sources_file(sources_file)

    assert entries == [
        {"line": 3, "source": "papers/local.pdf", "resolved_source": str(local_pdf)},
        {"line": 4, "source": "arxiv:2401.12345", "resolved_source": "arxiv:2401.12345"},
    ]


def test_resolve_source_list_continues_after_failure(tmp_path: Path):
    local_pdf = tmp_path / "local.pdf"
    local_pdf.write_bytes(b"%PDF-")
    entries = [
        {"line": 1, "source": "missing.pdf", "resolved_source": str(tmp_path / "missing.pdf")},
        {"line": 2, "source": "local.pdf", "resolved_source": str(local_pdf)},
    ]

    pdf_paths, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
    )

    assert pdf_paths == [local_pdf]
    assert report["summary"] == {
        "total": 2,
        "success": 1,
        "cached": 0,
        "duplicate": 0,
        "failed": 1,
        "skipped": 0,
        "pdfs": 1,
    }
    assert report["items"][0]["status"] == "failed"
    assert report["items"][1]["status"] == "success"


def test_resolve_source_list_deduplicates_canonical_arxiv_sources(tmp_path: Path, monkeypatch):
    downloaded_pdf = tmp_path / "downloads" / "arxiv-2401.12345.pdf"
    calls = []

    def fake_resolve(source, download_dir, force=False):
        calls.append(source)
        downloaded_pdf.parent.mkdir()
        downloaded_pdf.write_bytes(b"%PDF-")
        return [downloaded_pdf]

    monkeypatch.setattr(batch, "resolve_pdf_paths", fake_resolve)
    entries = [
        {"line": 1, "source": "arxiv:2401.12345", "resolved_source": "arxiv:2401.12345"},
        {
            "line": 2,
            "source": "https://arxiv.org/abs/2401.12345",
            "resolved_source": "https://arxiv.org/abs/2401.12345",
        },
    ]

    pdf_paths, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
    )

    assert pdf_paths == [downloaded_pdf]
    assert calls == ["arxiv:2401.12345"]
    assert report["summary"]["duplicate"] == 1
    assert report["items"][1]["duplicate_of_line"] == 1


def test_resolve_source_list_marks_existing_remote_pdf_as_cached(tmp_path: Path, monkeypatch):
    downloaded_pdf = tmp_path / "downloads" / "paper.pdf"
    downloaded_pdf.parent.mkdir()
    downloaded_pdf.write_bytes(b"%PDF-")
    monkeypatch.setattr(batch, "resolve_pdf_paths", lambda *_args, **_kwargs: [downloaded_pdf])
    entries = [
        {
            "line": 1,
            "source": "https://example.org/paper.pdf",
            "resolved_source": "https://example.org/paper.pdf",
        }
    ]

    _, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
    )

    assert report["items"][0]["status"] == "cached"
    assert report["summary"]["cached"] == 1


def test_import_report_redacts_url_credentials_and_query(tmp_path: Path, monkeypatch):
    downloaded_pdf = tmp_path / "downloads" / "paper.pdf"

    def fake_resolve(*_args, **_kwargs):
        downloaded_pdf.parent.mkdir()
        downloaded_pdf.write_bytes(b"%PDF-")
        return [downloaded_pdf]

    monkeypatch.setattr(batch, "resolve_pdf_paths", fake_resolve)
    private_url = "https://user:password@example.org/paper.pdf?token=secret#viewer"
    entries = [{"line": 1, "source": private_url, "resolved_source": private_url}]

    _, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
    )

    serialized_report = str(report)
    assert "password" not in serialized_report
    assert "secret" not in serialized_report
    assert report["items"][0]["source"] == "https://example.org/paper.pdf"


def test_resolve_source_list_fail_fast_skips_remaining_sources(tmp_path: Path):
    local_pdf = tmp_path / "local.pdf"
    local_pdf.write_bytes(b"%PDF-")
    entries = [
        {"line": 1, "source": "missing.pdf", "resolved_source": str(tmp_path / "missing.pdf")},
        {"line": 2, "source": "local.pdf", "resolved_source": str(local_pdf)},
    ]

    pdf_paths, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
        fail_fast=True,
    )

    assert pdf_paths == []
    assert report["stopped_early"] is True
    assert report["summary"]["failed"] == 1
    assert report["summary"]["skipped"] == 1
    assert report["items"][1]["status"] == "skipped"


def test_resolve_source_list_marks_empty_local_folder_as_failed(tmp_path: Path):
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()
    entries = [{"line": 1, "source": "empty", "resolved_source": str(empty_folder)}]

    pdf_paths, report = batch.resolve_source_list(
        entries,
        tmp_path / "downloads",
        sources_file=tmp_path / "sources.txt",
    )

    assert pdf_paths == []
    assert report["items"][0]["status"] == "failed"
    assert "No PDF files found" in report["items"][0]["error"]
