import os
from pathlib import Path

import pytest

from papermatrix.source import resolve_pdf_paths


RUN_NETWORK = os.getenv("PAPERMATRIX_RUN_INTEGRATION") == "1"


@pytest.mark.integration
@pytest.mark.skipif(not RUN_NETWORK, reason="set PAPERMATRIX_RUN_INTEGRATION=1 to run network tests")
def test_real_arxiv_download(tmp_path: Path):
    path = resolve_pdf_paths("arxiv:1706.03762", tmp_path / "downloads", retries=2)[0]

    assert path.read_bytes()[:1024].find(b"%PDF-") >= 0
    assert path.with_suffix(".source.json").exists()
