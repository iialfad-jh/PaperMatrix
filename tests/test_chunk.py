from pathlib import Path

from papermatrix.chunk import chunk_pages, load_chunks_jsonl, save_chunks_jsonl


def test_chunk_split_preserves_page_numbers():
    pages = [
        {"page": 1, "text": "a" * 20},
        {"page": 2, "text": "b" * 20},
        {"page": 3, "text": "c" * 20},
    ]

    chunks = chunk_pages(pages, paper_id="paper1", max_chars=45)

    assert chunks[0]["pages"] == [1, 2]
    assert chunks[1]["pages"] == [3]
    assert chunks[0]["chunk_id"] == "paper1_c0"


def test_chunks_jsonl_round_trip(tmp_path: Path):
    chunks = [
        {"chunk_id": "paper1_c0", "paper_id": "paper1", "pages": [1], "text": "first chunk"},
        {"chunk_id": "paper1_c1", "paper_id": "paper1", "pages": [2], "text": "second chunk"},
    ]
    path = tmp_path / "paper1_chunks.jsonl"

    save_chunks_jsonl(chunks, path)

    assert load_chunks_jsonl(path) == chunks


def test_chunk_pages_creates_table_chunk_without_page_text():
    pages = [
        {
            "page": 2,
            "text": "",
            "tables": [
                {
                    "table_index": 0,
                    "table_count": 1,
                    "strategy": "lines",
                    "bbox": [10, 20, 100, 200],
                    "header": ["Dataset", "Accuracy"],
                    "rows": [["TestSet", "92.4"]],
                }
            ],
        }
    ]

    chunks = chunk_pages(pages, paper_id="paper1")

    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == "paper1_t0"
    assert chunks[0]["kind"] == "table"
    assert chunks[0]["pages"] == [2]
    assert "| Dataset | Accuracy |" in chunks[0]["text"]
    assert chunks[0]["table"]["rows"] == [["TestSet", "92.4"]]


def test_chunk_pages_merges_matching_tables_across_adjacent_pages():
    pages = [
        {
            "page": 1,
            "text": "Results",
            "tables": [
                {
                    "table_index": 0,
                    "table_count": 1,
                    "header": ["Model", "Accuracy"],
                    "rows": [["Baseline", "88.1"]],
                }
            ],
        },
        {
            "page": 2,
            "text": "",
            "tables": [
                {
                    "table_index": 0,
                    "table_count": 1,
                    "header": ["Model", "Accuracy"],
                    "rows": [["Ours", "92.4"]],
                }
            ],
        },
    ]

    chunks = chunk_pages(pages, paper_id="paper1")
    table_chunks = [chunk for chunk in chunks if chunk.get("kind") == "table"]

    assert len(table_chunks) == 1
    assert table_chunks[0]["pages"] == [1, 2]
    assert table_chunks[0]["table"]["rows"] == [["Baseline", "88.1"], ["Ours", "92.4"]]


def test_chunk_pages_splits_large_tables_by_complete_rows():
    pages = [
        {
            "page": 3,
            "text": "",
            "tables": [
                {
                    "table_index": 0,
                    "table_count": 1,
                    "header": ["Model", "Accuracy"],
                    "rows": [[f"Model {index}", f"{80 + index}.0"] for index in range(8)],
                }
            ],
        }
    ]

    chunks = chunk_pages(pages, paper_id="paper1", max_chars=110)

    assert len(chunks) > 1
    assert all(chunk["kind"] == "table" for chunk in chunks)
    assert all("| Model | Accuracy |" in chunk["text"] for chunk in chunks)
    assert sum(len(chunk["table"]["rows"]) for chunk in chunks) == 8
