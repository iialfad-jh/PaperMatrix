from papermatrix.selector import select_chunks_for_extraction


def test_selector_picks_dataset_metric_result_chunks():
    chunks = [
        {"chunk_id": f"paper_c{i}", "paper_id": "paper", "pages": [i + 1], "text": f"neutral section {i}"}
        for i in range(15)
    ]
    chunks[6]["text"] = "We evaluate on a benchmark dataset and corpus."
    chunks[8]["text"] = "Metrics include accuracy, F1, precision, and recall."
    chunks[10]["text"] = "Results outperform baselines and improve performance."
    chunks[14]["text"] = "References Smith 2020."

    selected = select_chunks_for_extraction(chunks, max_chunks=8)
    selected_ids = {chunk["chunk_id"] for chunk in selected}

    assert "paper_c6" in selected_ids
    assert "paper_c8" in selected_ids
    assert "paper_c10" in selected_ids


def test_selector_uses_section_headings_as_relevance_signals():
    chunks = [
        {"chunk_id": f"paper_c{i}", "paper_id": "paper", "pages": [i + 1], "text": f"neutral section {i}"}
        for i in range(16)
    ]
    chunks[7]["text"] = "3 Technical Design We align early images with future observations before synthesis."
    chunks[8]["text"] = "4 Experimental Setup Images were captured weekly across cultivars and seasons."

    selected = select_chunks_for_extraction(chunks, max_chunks=5)
    selected_ids = {chunk["chunk_id"] for chunk in selected}

    assert "paper_c7" in selected_ids
    assert "paper_c8" in selected_ids


def test_selector_uses_custom_field_names_as_keywords():
    chunks = [
        {"chunk_id": f"paper_c{i}", "paper_id": "paper", "pages": [i + 1], "text": f"neutral section {i}"}
        for i in range(14)
    ]
    chunks[6]["text"] = "The model input contains early side-view images and treatment metadata."
    chunks[9]["text"] = "The output is a predicted future canopy image."

    selected = select_chunks_for_extraction(chunks, max_chunks=5, field_names=["input", "output"])
    selected_ids = {chunk["chunk_id"] for chunk in selected}

    assert "paper_c6" in selected_ids
    assert "paper_c9" in selected_ids
