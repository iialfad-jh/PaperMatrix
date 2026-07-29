import json
from pathlib import Path

import pytest

from papermatrix.pipeline import (
    CancellationToken,
    PipelineConfig,
    PipelineError,
    ProgressEvent,
    resolve_project_dir,
    run_pipeline,
)
from papermatrix.schema import Evidence, ExtractedField, PaperExtract, field_specs_from_names


def make_config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        out=tmp_path / "matrix.md",
        work_dir=tmp_path / ".papermatrix",
        language="en",
        field_specs=tuple(field_specs_from_names(["problem"])),
        llm_config={"model": "test-model", "api_mode": "chat", "base_url": ""},
        retries=0,
    )


def fake_read_pdf_pages(_path: str | Path) -> list[dict]:
    return [{"page": 1, "text": "This paper studies resumable document extraction."}]


def fake_extract_paper(paper_id, selected_chunks, _llm_client, **_kwargs) -> PaperExtract:
    return PaperExtract(
        paper_id=paper_id,
        title="Resumable Extraction",
        fields={
            "problem": ExtractedField(
                value="reliable document extraction",
                evidence=[Evidence(chunk_id=selected_chunks[0]["chunk_id"], pages=[1])],
            )
        },
    )


def test_run_pipeline_emits_structured_progress_and_exports_results(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    events: list[ProgressEvent] = []

    result = run_pipeline(
        make_config(tmp_path),
        [(pdf_path, "paper")],
        lambda: object(),
        progress_callback=events.append,
        read_pdf_pages_fn=fake_read_pdf_pages,
        extract_paper_fn=fake_extract_paper,
    )

    assert result.success
    assert not result.cancelled
    assert result.markdown_path == tmp_path / "matrix.md"
    assert result.csv_path == tmp_path / "matrix.csv"
    assert result.evidence_path == tmp_path / "matrix.evidence.md"
    assert result.run_report["items"][0]["status"] == "exported"
    assert (tmp_path / ".papermatrix" / "paper_extract.json").exists()
    assert [(event.phase, event.status) for event in events] == [
        ("run", "started"),
        ("pdf", "started"),
        ("pdf", "completed"),
        ("llm", "started"),
        ("llm", "completed"),
        ("paper", "completed"),
        ("export", "completed"),
        ("run", "completed"),
    ]
    assert events[2].payload["pages"] == 1
    assert events[2].as_dict()["paper_id"] == "paper"


def test_run_pipeline_persists_pre_cancelled_papers(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    token = CancellationToken()
    token.cancel()

    result = run_pipeline(
        make_config(tmp_path),
        [(pdf_path, "paper")],
        lambda: object(),
        cancellation_token=token,
        read_pdf_pages_fn=fake_read_pdf_pages,
        extract_paper_fn=fake_extract_paper,
    )

    assert not result.success
    assert result.cancelled
    assert result.run_report["summary"]["cancelled"] == 1
    assert result.run_report["items"][0]["status"] == "cancelled"
    saved_report = json.loads(result.run_report_path.read_text(encoding="utf-8"))
    assert saved_report["items"][0]["status"] == "cancelled"
    assert not (tmp_path / "matrix.md").exists()


def test_progress_callback_failure_does_not_abort_pipeline(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def broken_callback(_event: ProgressEvent) -> None:
        raise RuntimeError("UI listener disconnected")

    result = run_pipeline(
        make_config(tmp_path),
        [(pdf_path, "paper")],
        lambda: object(),
        progress_callback=broken_callback,
        read_pdf_pages_fn=fake_read_pdf_pages,
        extract_paper_fn=fake_extract_paper,
    )

    assert result.success
    assert (tmp_path / "matrix.md").exists()


def test_resolve_project_dir_is_stable_and_traversal_safe(tmp_path: Path):
    assert resolve_project_dir(tmp_path, "review_2026") == tmp_path / "projects" / "review_2026"
    assert resolve_project_dir(tmp_path) == tmp_path

    with pytest.raises(ValueError, match="project_id"):
        resolve_project_dir(tmp_path, "../outside")


@pytest.mark.parametrize("paper_id", ["../outside", "folder/paper", "folder\\paper"])
def test_run_pipeline_rejects_unsafe_paper_ids(tmp_path: Path, paper_id: str):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(PipelineError, match="invalid paper_id"):
        run_pipeline(make_config(tmp_path), [(pdf_path, paper_id)], lambda: object())


def test_run_pipeline_rejects_retry_report_mismatch(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    retry_state = {
        "config": {},
        "items": [
            {
                "paper_id": "other",
                "pdf_path": str(pdf_path),
                "status": "llm_failed",
                "stages": ["imported"],
            }
        ],
    }

    with pytest.raises(PipelineError, match="does not contain paper_id"):
        run_pipeline(
            make_config(tmp_path),
            [(pdf_path, "paper")],
            lambda: object(),
            retry_state=retry_state,
        )
