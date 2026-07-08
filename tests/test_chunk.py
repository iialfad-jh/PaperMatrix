from papermatrix.chunk import chunk_pages


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
