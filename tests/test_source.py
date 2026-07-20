from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from papermatrix import source


class FakeResponse(BytesIO):
    def __init__(self, content: bytes, headers: dict[str, str] | None = None):
        super().__init__(content)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@pytest.mark.parametrize(
    ("input_source", "expected_url", "expected_name"),
    [
        ("arxiv:2401.12345", "https://arxiv.org/pdf/2401.12345.pdf", "arxiv-2401.12345.pdf"),
        ("https://arxiv.org/abs/2401.12345v2", "https://arxiv.org/pdf/2401.12345v2.pdf", "arxiv-2401.12345v2.pdf"),
        ("https://arxiv.org/pdf/2401.12345.pdf", "https://arxiv.org/pdf/2401.12345.pdf", "arxiv-2401.12345.pdf"),
    ],
)
def test_resolve_arxiv_sources(tmp_path: Path, monkeypatch, input_source: str, expected_url: str, expected_name: str):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append((request.full_url, timeout))
        return FakeResponse(b"%PDF-1.7\ntest")

    monkeypatch.setattr(source, "urlopen", fake_urlopen)

    paths = source.resolve_pdf_paths(input_source, tmp_path / "downloads")

    assert paths == [tmp_path / "downloads" / expected_name]
    assert paths[0].read_bytes().startswith(b"%PDF-")
    assert requested_urls == [(expected_url, 30)]


def test_direct_pdf_url_uses_download_cache(tmp_path: Path, monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(b"%PDF-1.4\ntest")

    monkeypatch.setattr(source, "urlopen", fake_urlopen)
    url = "https://example.org/files/My%20Paper.pdf?download=1"

    first = source.resolve_pdf_paths(url, tmp_path / "downloads")
    second = source.resolve_pdf_paths(url, tmp_path / "downloads")

    assert first == second
    assert first[0].name.startswith("My_Paper-")
    assert calls == [url]


def test_force_redownloads_remote_pdf(tmp_path: Path, monkeypatch):
    contents = [b"%PDF-1.4\nfirst", b"%PDF-1.4\nsecond"]

    def fake_urlopen(_request, timeout):
        assert timeout == 30
        return FakeResponse(contents.pop(0))

    monkeypatch.setattr(source, "urlopen", fake_urlopen)
    url = "https://example.org/paper.pdf"

    path = source.resolve_pdf_paths(url, tmp_path / "downloads")[0]
    refreshed_path = source.resolve_pdf_paths(url, tmp_path / "downloads", force=True)[0]

    assert path == refreshed_path
    assert refreshed_path.read_bytes().endswith(b"second")


def test_rejects_non_pdf_download(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source, "urlopen", lambda *_args, **_kwargs: FakeResponse(b"<html>not a pdf</html>"))

    with pytest.raises(source.SourceError, match="not a PDF"):
        source.resolve_pdf_paths("https://example.org/article", tmp_path / "downloads")


def test_local_folder_still_returns_pdf_files(tmp_path: Path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "b.pdf").write_bytes(b"%PDF-")
    (papers / "a.pdf").write_bytes(b"%PDF-")
    (papers / "notes.txt").write_text("ignore", encoding="utf-8")

    assert source.resolve_pdf_paths(str(papers), tmp_path / "downloads") == [papers / "a.pdf", papers / "b.pdf"]
