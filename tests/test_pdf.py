from pathlib import Path

import pymupdf as fitz

from papermatrix import pdf


def test_read_pdf_pages_extracts_a_real_table_with_empty_cells(tmp_path: Path):
    pdf_path = tmp_path / "table.pdf"
    document = fitz.open()
    page = document.new_page()
    x_positions = [72, 210, 340]
    y_positions = [72, 108, 144, 180]
    for x in x_positions:
        page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
    for y in y_positions:
        page.draw_line((x_positions[0], y), (x_positions[-1], y))
    page.insert_text((82, 96), "Model", fontsize=10)
    page.insert_text((220, 96), "Accuracy", fontsize=10)
    page.insert_text((82, 132), "Baseline", fontsize=10)
    page.insert_text((82, 168), "Ours", fontsize=10)
    page.insert_text((220, 168), "92.4", fontsize=10)
    document.save(pdf_path)
    document.close()

    pages = pdf.read_pdf_pages(pdf_path)

    assert len(pages) == 1
    assert len(pages[0]["tables"]) == 1
    table = pages[0]["tables"][0]
    assert table["header"] == ["Model", "Accuracy"]
    assert table["rows"] == [["Baseline", ""], ["Ours", "92.4"]]
    assert table["page"] == 1


def test_table_detection_failure_falls_back_to_page_text(tmp_path: Path, monkeypatch):
    class FakePage:
        def get_text(self, _kind):
            return "Readable page text."

        def find_tables(self, **_kwargs):
            raise RuntimeError("table detector failed")

    class FakeDocument:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __iter__(self):
            return iter([FakePage()])

    monkeypatch.setattr(pdf.fitz, "open", lambda _path: FakeDocument())

    pages = pdf.read_pdf_pages(tmp_path / "paper.pdf")

    assert pages == [{"page": 1, "text": "Readable page text.", "tables": []}]


def test_table_detection_uses_text_strategy_when_lines_find_nothing(tmp_path: Path, monkeypatch):
    calls = []

    class FakeHeader:
        names = ["Dataset", "Score"]

    class FakeTable:
        header = FakeHeader()
        bbox = (10, 20, 100, 200)

        def extract(self):
            return [["Dataset", "Score"], ["Benchmark", "91.2"]]

    class FakeFinder:
        def __init__(self, tables):
            self.tables = tables

    class FakePage:
        rect = fitz.Rect(0, 0, 600, 800)

        def get_text(self, _kind):
            return "Benchmark results."

        def find_tables(self, **kwargs):
            calls.append(kwargs)
            return FakeFinder([FakeTable()] if kwargs.get("strategy") == "text" else [])

    class FakeDocument:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __iter__(self):
            return iter([FakePage()])

    monkeypatch.setattr(pdf.fitz, "open", lambda _path: FakeDocument())

    pages = pdf.read_pdf_pages(tmp_path / "paper.pdf")

    assert calls == [{}, {"strategy": "text"}]
    assert pages[0]["tables"][0]["strategy"] == "text"
    assert pages[0]["tables"][0]["rows"] == [["Benchmark", "91.2"]]


def test_text_strategy_rejects_full_page_column_layout(tmp_path: Path, monkeypatch):
    class FakeHeader:
        names = ["Journal header", "Page number"]

    class FakeTable:
        header = FakeHeader()
        bbox = (50, 30, 550, 750)

        def extract(self):
            return [["Journal header", "Page number"], ["Column one", "Column two"]]

    class FakeFinder:
        def __init__(self, tables):
            self.tables = tables

    class FakePage:
        rect = fitz.Rect(0, 0, 600, 800)

        def get_text(self, _kind):
            return "Two-column article text."

        def find_tables(self, **kwargs):
            return FakeFinder([FakeTable()] if kwargs.get("strategy") == "text" else [])

    class FakeDocument:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __iter__(self):
            return iter([FakePage()])

    monkeypatch.setattr(pdf.fitz, "open", lambda _path: FakeDocument())

    pages = pdf.read_pdf_pages(tmp_path / "paper.pdf")

    assert pages[0]["tables"] == []
