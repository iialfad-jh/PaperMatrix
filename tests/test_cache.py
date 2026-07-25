from pathlib import Path

from papermatrix.cache import build_cache_metadata, is_cache_metadata_current


def test_pre_table_cache_version_is_invalidated(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-")
    current = build_cache_metadata(
        pdf_path,
        language="en",
        llm_config={"model": "test", "api_mode": "chat", "base_url": ""},
        max_chars=3500,
        max_chunks=12,
        field_names=["result"],
    )
    old = {**current, "cache_version": 2}

    assert current["cache_version"] == 3
    assert not is_cache_metadata_current(old, current)
