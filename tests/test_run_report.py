from pathlib import Path

from papermatrix.run_report import create_run_report, failed_items, load_run_report, record_failure, save_run_report


class RateLimitError(Exception):
    status_code = 429


def test_run_report_records_failures_and_round_trips(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-")
    report = create_run_report(
        {"retries": 2, "out": str(tmp_path / "matrix.md")},
        [(pdf_path, "paper")],
    )

    record_failure(report["items"][0], "llm_failed", RateLimitError("try later"))
    report_path = save_run_report(report, tmp_path / ".papermatrix" / "run-report.json")
    loaded = load_run_report(report_path)

    assert loaded["summary"]["total"] == 1
    assert loaded["summary"]["llm_failed"] == 1
    assert loaded["items"][0]["error"] == {
        "type": "RateLimitError",
        "message": "try later",
        "transient": True,
        "status_code": 429,
    }
    assert failed_items(loaded) == loaded["items"]
    assert not report_path.with_suffix(".json.tmp").exists()


def test_skipped_items_are_retryable(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    report = create_run_report({"retries": 0}, [(pdf_path, "paper")])
    report["items"][0]["status"] = "skipped"

    assert failed_items(report) == report["items"]
