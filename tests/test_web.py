import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from papermatrix import cli
from papermatrix.pipeline import PipelineResult, ProgressEvent
from papermatrix.run_report import create_run_report, save_run_report
from papermatrix.web import JobManager, create_app


def wait_for_status(client: TestClient, job_id: str, expected: set[str], timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in expected:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def write_success_result(config, paper_plan, run_report_path: Path, progress_callback) -> PipelineResult:
    progress_callback(ProgressEvent("pdf", "started", paper_id="paper", filename="paper.pdf", index=1, total=1))
    progress_callback(ProgressEvent("llm", "completed", paper_id="paper", filename="paper.pdf", index=1, total=1))
    config.out.parent.mkdir(parents=True, exist_ok=True)
    config.out.write_text("# Matrix\n", encoding="utf-8")
    csv_path = config.out.with_suffix(".csv")
    csv_path.write_text("Paper,Problem\nExample Paper,Example problem\n", encoding="utf-8")
    evidence_path = config.out.with_suffix(".evidence.md")
    evidence_path.write_text("# Evidence\n\nPage 1", encoding="utf-8")
    report = create_run_report(config.report_config(), paper_plan)
    report["items"][0]["status"] = "exported"
    report["items"][0]["stages"].extend(["extracted", "exported"])
    save_run_report(report, run_report_path)
    return PipelineResult(True, False, [], report, run_report_path, config.out, csv_path, evidence_path)


def test_web_job_upload_streams_progress_and_previews_results(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "web-test", "language": "en", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        job = wait_for_status(client, job_id, {"completed"})
        assert job["project_id"] == "web-test"
        assert set(job["artifacts"]) == {"markdown", "csv", "evidence", "report", "import_report"}
        assert job["summary"]["exported"] == 1

        preview = client.get(f"/api/jobs/{job_id}/preview")
        assert preview.status_code == 200
        assert preview.json()["columns"] == ["Paper", "Problem"]
        assert preview.json()["rows"][0]["Paper"] == "Example Paper"
        assert "Page 1" in preview.json()["evidence"]

        events = client.get(f"/api/jobs/{job_id}/events").text
        assert '"type":"progress"' in events
        assert '"status":"completed"' in events


def test_web_rejects_unsafe_project_ids_and_non_pdf_uploads(tmp_path: Path):
    with TestClient(create_app(tmp_path)) as client:
        unsafe = client.post(
            "/api/jobs",
            data={"project_id": "../outside", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        wrong_type = client.post(
            "/api/jobs",
            data={"project_id": "safe-project", "preset": "general"},
            files={"files": ("notes.txt", b"not a pdf", "text/plain")},
        )

    assert unsafe.status_code == 422
    assert "project_id" in unsafe.json()["detail"]
    assert wrong_type.status_code == 422
    assert "Only PDF" in wrong_type.json()["detail"]


def test_web_accepts_a_text_source_without_a_selected_upload(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "text-source", "preset": "general", "source": str(pdf_path)},
        )

        assert response.status_code == 202, response.text
        final = wait_for_status(client, response.json()["id"], {"completed"})

    assert final["summary"]["exported"] == 1


def test_web_reuses_the_same_content_addressed_upload(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        first_response = client.post(
            "/api/jobs",
            data={"project_id": "stable-upload", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\nstable", "application/pdf")},
        )
        first = wait_for_status(client, first_response.json()["id"], {"completed"})
        first_path = manager.get(first["id"]).spec.uploaded_paths[0]

        second_response = client.post(
            "/api/jobs",
            data={"project_id": "stable-upload", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\nstable", "application/pdf")},
        )
        second = wait_for_status(client, second_response.json()["id"], {"completed"})
        second_path = manager.get(second["id"]).spec.uploaded_paths[0]

    assert first_path == second_path
    assert first_path.name.endswith("-paper.pdf")
    assert first_path.is_file()


def test_web_cancels_a_running_job(tmp_path: Path):
    runner_started = threading.Event()

    def runner(config, paper_plan, _llm_factory, **kwargs):
        runner_started.set()
        token = kwargs["cancellation_token"]
        deadline = time.monotonic() + 2
        while not token.is_cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        report = create_run_report(config.report_config(), paper_plan)
        report["items"][0]["status"] = "cancelled"
        report["items"][0]["stages"].append("cancelled")
        report_path = Path(kwargs["run_report_path"])
        save_run_report(report, report_path)
        return PipelineResult(False, True, [], report, report_path)

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        created = client.post(
            "/api/jobs",
            data={"project_id": "cancel-test", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        ).json()
        assert runner_started.wait(1)
        cancelled = client.post(f"/api/jobs/{created['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelling"
        final = wait_for_status(client, created["id"], {"cancelled"})

    assert final["summary"]["cancelled"] == 1
    assert final["can_retry"]


def test_web_retries_only_failed_items_from_the_run_report(tmp_path: Path):
    calls = 0

    def runner(config, paper_plan, _llm_factory, **kwargs):
        nonlocal calls
        calls += 1
        report_path = Path(kwargs["run_report_path"])
        if calls == 1:
            report = create_run_report(config.report_config(), paper_plan)
            report["items"][0]["status"] = "llm_failed"
            report["items"][0]["error"] = {"type": "RuntimeError", "message": "temporary failure"}
            save_run_report(report, report_path)
            return PipelineResult(False, False, [], report, report_path)
        assert kwargs["retry_state"] is not None
        return write_success_result(config, paper_plan, report_path, kwargs["progress_callback"])

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        created = client.post(
            "/api/jobs",
            data={"project_id": "retry-test", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        ).json()
        failed = wait_for_status(client, created["id"], {"failed"})
        assert failed["can_retry"]

        retried_response = client.post(f"/api/jobs/{created['id']}/retry")
        assert retried_response.status_code == 202, retried_response.text
        retried = wait_for_status(client, retried_response.json()["id"], {"completed"})

    assert calls == 2
    assert retried["summary"]["exported"] == 1


def test_cli_web_source_dispatches_to_local_server(monkeypatch):
    captured = {}

    def fake_serve(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("papermatrix.web.serve", fake_serve)
    result = CliRunner().invoke(cli.app, ["web", "--no-open", "--port", "9012"])

    assert result.exit_code == 0, result.output
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9012
    assert not captured["open_browser"]
