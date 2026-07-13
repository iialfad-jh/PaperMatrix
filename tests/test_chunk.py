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
