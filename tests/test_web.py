import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from papermatrix import cli
from papermatrix.chunk import save_chunks_jsonl
from papermatrix.extract import save_extract_json
from papermatrix.pipeline import PipelineResult, ProgressEvent
from papermatrix.run_report import create_run_report, save_run_report
from papermatrix.schema import Evidence, ExtractedField, PaperExtract
from papermatrix.web import SESSION_COOKIE_NAME, JobManager, _classify_service_error, create_app


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
    paper_id = paper_plan[0][1]
    save_chunks_jsonl(
        [
            {
                "chunk_id": f"{paper_id}_c0",
                "paper_id": paper_id,
                "pages": [1],
                "text": "Example problem evidence from the first page.",
            }
        ],
        config.work_dir / f"{paper_id}_chunks.jsonl",
    )
    save_extract_json(
        PaperExtract(
            paper_id=paper_id,
            title="Example Paper",
            fields={
                "problem": ExtractedField(
                    value="Example problem",
                    evidence=[Evidence(chunk_id=f"{paper_id}_c0", pages=[1])],
                )
            },
        ),
        config.work_dir / f"{paper_id}_extract.json",
    )
    return PipelineResult(True, False, [], report, run_report_path, config.out, csv_path, evidence_path)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ProviderError("The api_key client option must be set"), "api_key_missing"),
        (ProviderError("Incorrect API key provided", 401), "api_key_invalid"),
        (ProviderError("DNS name resolution failed"), "network_unreachable"),
        (ProviderError("The requested model does not exist", 404), "model_not_found"),
        (ProviderError("This endpoint is not supported for chat completions", 400), "api_mode_incompatible"),
        (ProviderError("insufficient_quota", 429), "rate_or_quota_limit"),
        (ProviderError("Request timed out"), "request_timeout"),
        (ProviderError("SSL certificate verify failed"), "tls_or_proxy"),
    ],
)
def test_web_classifies_actionable_provider_errors(error: Exception, expected_code: str):
    detail = _classify_service_error(error)

    assert detail["code"] == expected_code
    assert detail["title"]
    assert detail["message"]
    assert detail["action"]
    assert detail["technical"]


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
        assert preview.json()["field_names"] == ["problem", "method", "dataset", "metric", "result", "limitation"]
        assert "Page 1" in preview.json()["evidence"]

        report = json.loads(manager.get(job_id).run_report_path.read_text(encoding="utf-8"))
        paper_id = report["items"][0]["paper_id"]
        assert preview.json()["paper_ids"] == [paper_id]
        evidence = client.get(f"/api/jobs/{job_id}/papers/{paper_id}/fields/problem/evidence")
        assert evidence.status_code == 200
        assert evidence.json()["title"] == "Example Paper"
        assert evidence.json()["pdf_url"] == f"/api/jobs/{job_id}/papers/{paper_id}/pdf"
        assert evidence.json()["field"] == {
            "name": "problem",
            "label": "Problem",
            "value": "Example problem",
            "evidence": [
                {
                    "chunk_id": f"{paper_id}_c0",
                    "pages": [1],
                    "text": "Example problem evidence from the first page.",
                    "kind": "text",
                    "table": None,
                }
            ],
        }

        pdf = client.get(f"/api/jobs/{job_id}/papers/{paper_id}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.headers["content-disposition"].startswith("inline;")
        assert pdf.content == b"%PDF-1.4\n"

        assert client.get(f"/api/jobs/{job_id}/papers/not-a-paper/pdf").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/papers/{paper_id}/fields/not_a_field/evidence").status_code == 404

        events = client.get(f"/api/jobs/{job_id}/events").text
        assert '"type":"progress"' in events
        assert '"status":"completed"' in events


def test_web_stores_results_in_selected_folder_and_reads_markdown_history(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    results_dir = tmp_path / "PaperMatrix Results" / "literature-results"
    legacy_dir = results_dir / "previous-review"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "notes.md").write_text("# Existing review\n", encoding="utf-8")

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        config = client.get("/api/config").json()
        assert config["defaults"]["results_dir"] == str(tmp_path / "PaperMatrix Results")

        response = client.post(
            "/api/jobs",
            data={"project_id": "history-test", "preset": "general", "results_dir": str(results_dir)},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert response.status_code == 202, response.text
        final = wait_for_status(client, response.json()["id"], {"completed"})
        assert set(final["artifacts"]) == {"markdown", "csv", "evidence", "report", "import_report"}

        history = client.get("/api/history", params={"results_dir": str(results_dir)})
        assert history.status_code == 200, history.text
        paths = {file["path"] for file in history.json()["files"]}
        assert {"previous-review/notes.md", "history-test/matrix.md", "history-test/matrix.evidence.md"} <= paths

        markdown = client.get(
            "/api/history/file",
            params={"results_dir": str(results_dir), "path": "history-test/matrix.md"},
        )
        assert markdown.status_code == 200
        assert markdown.json() == {"path": "history-test/matrix.md", "content": "# Matrix\n"}

        escaped = client.get(
            "/api/history/file",
            params={"results_dir": str(results_dir), "path": "../outside.md"},
        )
        assert escaped.status_code == 422

    output_dir = results_dir / "history-test"
    assert {path.name for path in output_dir.iterdir()} >= {
        "matrix.md",
        "matrix.csv",
        "matrix.evidence.md",
        "run-report.json",
        "import-report.json",
    }
    assert manager.get(final["id"]).spec.results_dir == results_dir.resolve()


def test_web_restricts_results_to_the_configured_root(tmp_path: Path):
    manager = JobManager(tmp_path)
    outside = tmp_path / "outside-results"

    with TestClient(create_app(tmp_path, manager=manager)) as client:
        history = client.get("/api/history", params={"results_dir": str(outside)})
        submitted = client.post(
            "/api/jobs",
            data={"project_id": "outside-results", "preset": "general", "results_dir": str(outside)},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert history.status_code == 422
    assert submitted.status_code == 422
    assert "configured results root" in history.json()["detail"]
    assert not outside.exists()


def test_web_server_mode_requires_a_session_and_rejects_local_sources(tmp_path: Path):
    local_pdf = tmp_path / "server-private.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\n")
    manager = JobManager(tmp_path, allow_local_sources=False)

    with TestClient(create_app(tmp_path, manager=manager, auth_token="workspace-token"), base_url="https://testserver") as client:
        assert client.get("/api/config").status_code == 401
        assert client.post("/api/session", data={"access_token": "wrong"}).status_code == 401
        session = client.post("/api/session", data={"access_token": "workspace-token"})
        assert session.status_code == 200
        assert SESSION_COOKIE_NAME in session.headers["set-cookie"]
        assert "HttpOnly" in session.headers["set-cookie"]
        assert "Secure" in session.headers["set-cookie"]
        assert client.get("/api/config").status_code == 200

        response = client.post(
            "/api/jobs",
            data={"project_id": "server-local", "preset": "general", "source": str(local_pdf)},
        )

    assert response.status_code == 422
    assert "not server-local paths" in response.json()["detail"]


def test_web_restores_completed_jobs_after_restart(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    first_manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=first_manager)) as client:
        created = client.post(
            "/api/jobs",
            data={"project_id": "persistent-job", "preset": "general"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        ).json()
        completed = wait_for_status(client, created["id"], {"completed"})

    restarted_manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=restarted_manager)) as client:
        restored = client.get(f"/api/jobs/{completed['id']}")
        listed = client.get("/api/jobs")

    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"
    assert restored.json()["artifacts"]["markdown"]
    assert [job["id"] for job in listed.json()["jobs"]] == [completed["id"]]


def test_web_accepts_a_reverse_proxy_root_path(tmp_path: Path):
    app = create_app(tmp_path, root_path="/papermatrix")
    assert app.root_path == "/papermatrix"


def test_web_job_surfaces_the_run_report_failure_reason(tmp_path: Path):
    def runner(config, paper_plan, _llm_factory, **kwargs):
        report = create_run_report(config.report_config(), paper_plan)
        report["items"][0]["status"] = "llm_failed"
        report["items"][0]["error"] = {
            "type": "AuthenticationError",
            "message": "Incorrect API key provided: sk-job-secret",
            "transient": False,
            "status_code": 401,
        }
        report_path = Path(kwargs["run_report_path"])
        save_run_report(report, report_path)
        return PipelineResult(False, False, [], report, report_path)

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "classified-failure", "preset": "general", "api_key": "sk-job-secret"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        final = wait_for_status(client, response.json()["id"], {"failed"})

    assert final["error_detail"]["code"] == "api_key_invalid"
    assert final["error_detail"]["title"] == "API Key 无效或无权限"
    assert "sk-job-secret" not in final["error_detail"]["technical"]
    assert "No paper could be exported" not in final["error"]


def test_web_job_summarizes_mixed_paper_failures(tmp_path: Path):
    secret = "sk-mixed-secret"

    def runner(config, paper_plan, _llm_factory, **kwargs):
        report = create_run_report(config.report_config(), paper_plan)
        report["items"][0]["status"] = "exported"
        report["items"][0]["stages"].extend(["extracted", "exported"])
        report["items"][1]["status"] = "llm_failed"
        report["items"][1]["error"] = {
            "type": "RateLimitError",
            "message": f"quota exhausted for {secret}",
            "transient": True,
            "status_code": 429,
        }
        report["items"][2]["status"] = "pdf_failed"
        report["items"][2]["error"] = {
            "type": "FileDataError",
            "message": "cannot open broken PDF",
            "transient": False,
            "status_code": None,
        }
        report_path = Path(kwargs["run_report_path"])
        save_run_report(report, report_path)
        return PipelineResult(False, False, [], report, report_path)

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "mixed-failure", "preset": "general", "api_key": secret},
            files=[
                ("files", ("ok.pdf", b"%PDF-1.4\nok", "application/pdf")),
                ("files", ("quota.pdf", b"%PDF-1.4\nquota", "application/pdf")),
                ("files", ("broken.pdf", b"%PDF-1.4\nbroken", "application/pdf")),
            ],
        )
        final = wait_for_status(client, response.json()["id"], {"failed"})

    summary = final["error_detail"]["failure_summary"]
    assert final["summary"]["total"] == 3
    assert final["summary"]["exported"] == 1
    assert final["error_detail"]["code"] == "rate_or_quota_limit"
    assert "已导出 1/3 篇论文，2 篇失败" in final["error"]
    assert summary["total"] == 3
    assert summary["exported"] == 1
    assert summary["failed"] == 2
    assert [group["code"] for group in summary["groups"]] == ["rate_or_quota_limit", "pdf_processing"]
    assert any("quota.pdf" in paper["filename"] for paper in summary["groups"][0]["papers"])
    assert any("broken.pdf" in paper["filename"] for paper in summary["groups"][1]["papers"])
    assert secret not in json.dumps(final, ensure_ascii=False)


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


def test_web_passes_selected_reasoning_effort_to_the_pipeline(tmp_path: Path):
    captured = {}

    def runner(config, paper_plan, _llm_factory, **kwargs):
        captured.update(config.llm_config)
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        config_response = client.get("/api/config")
        assert config_response.json()["defaults"]["model"] == "gpt-5.5"
        assert config_response.json()["defaults"]["reasoning_effort"] == "auto"

        response = client.post(
            "/api/jobs",
            data={
                "project_id": "reasoning-test",
                "preset": "general",
                "model": "gpt-5.5",
                "api_mode": "responses",
                "reasoning_effort": "medium",
            },
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert response.status_code == 202, response.text
        wait_for_status(client, response.json()["id"], {"completed"})

    assert captured["reasoning_effort"] == "medium"


def test_web_rejects_invalid_reasoning_effort(tmp_path: Path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "bad-reasoning", "preset": "general", "reasoning_effort": "extreme"},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )

    assert response.status_code == 422
    assert "reasoning_effort" in response.json()["detail"]


def test_web_passes_api_key_in_memory_without_persisting_it(tmp_path: Path, monkeypatch):
    captured = {}
    secret = "sk-local-secret"

    class FakeOpenAILLMClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("papermatrix.web.OpenAILLMClient", FakeOpenAILLMClient)

    def runner(config, paper_plan, llm_factory, **kwargs):
        llm_factory()
        assert "api_key" not in config.llm_config
        return write_success_result(config, paper_plan, Path(kwargs["run_report_path"]), kwargs["progress_callback"])

    manager = JobManager(tmp_path, pipeline_runner=runner)
    with TestClient(create_app(tmp_path, manager=manager)) as client:
        response = client.post(
            "/api/jobs",
            data={"project_id": "api-key-test", "preset": "general", "api_key": secret},
            files={"files": ("paper.pdf", b"%PDF-1.4\n", "application/pdf")},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        wait_for_status(client, job_id, {"completed"})

    job = manager.get(job_id)
    assert captured["api_key"] == secret
    assert secret not in response.text
    assert secret not in repr(job.spec)
    assert job.run_report_path is not None
    assert secret not in job.run_report_path.read_text(encoding="utf-8")


def test_web_provider_probe_uses_current_configuration_without_exposing_key(tmp_path: Path, monkeypatch):
    captured = {}
    secret = "sk-probe-secret"

    class FakeOpenAILLMClient:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def extract_json(self, paper_id, chunks, **kwargs):
            captured["probe"] = {"paper_id": paper_id, "chunks": chunks, **kwargs}
            return {"paper_id": paper_id, "title": "Probe", "fields": {}}

        def config_summary(self):
            return {
                "model": captured["kwargs"]["model"],
                "api_mode": captured["kwargs"]["api_mode"],
                "reasoning_effort": captured["kwargs"]["reasoning_effort"],
                "base_url": captured["kwargs"]["base_url"],
                "language": captured["kwargs"]["language"],
            }

    monkeypatch.setattr("papermatrix.web.OpenAILLMClient", FakeOpenAILLMClient)

    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/provider-probe",
            data={
                "language": "en",
                "model": "gpt-5.5",
                "api_key": secret,
                "base_url": "https://relay.example/v1",
                "api_mode": "responses",
                "reasoning_effort": "low",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["config"]["model"] == "gpt-5.5"
    assert secret not in response.text
    assert captured["kwargs"]["api_key"] == secret
    assert captured["kwargs"]["max_retries"] == 0
    assert captured["probe"]["paper_id"] == "provider-probe"
    assert captured["probe"]["field_names"] == ["problem"]


def test_web_provider_probe_sanitizes_failures_and_validates_config(tmp_path: Path, monkeypatch):
    secret = "sk-probe-secret"

    class FailingOpenAILLMClient:
        def __init__(self, **_kwargs):
            pass

        def extract_json(self, *_args, **_kwargs):
            raise RuntimeError(f"provider rejected {secret}")

    monkeypatch.setattr("papermatrix.web.OpenAILLMClient", FailingOpenAILLMClient)

    with TestClient(create_app(tmp_path)) as client:
        failed = client.post("/api/provider-probe", data={"api_key": secret})
        invalid = client.post("/api/provider-probe", data={"reasoning_effort": "extreme"})

    assert failed.status_code == 502
    assert "RuntimeError" in failed.json()["detail"]
    assert secret not in failed.text
    assert "***" in failed.json()["detail"]
    assert failed.json()["error"]["code"] == "unknown"
    assert failed.json()["error"]["title"] == "模型服务请求失败"
    assert failed.json()["error"]["action"]
    assert invalid.status_code == 422
    assert "reasoning_effort" in invalid.json()["detail"]


def test_web_ui_exposes_browser_local_settings_persistence(tmp_path: Path):
    with TestClient(create_app(tmp_path)) as client:
        page = client.get("/")
        script = client.get("/assets/app.js")

    assert page.status_code == 200
    assert 'id="remember-api-key"' in page.text
    assert "记住 API Key（仅此浏览器）" in page.text
    assert script.status_code == 200
    assert 'settingsStorageKey = "papermatrix.web.settings.v1"' in script.text
    assert "localStorage.setItem" in script.text
    assert "restoreSettings()" in script.text
    assert "job.error_detail || job.error" in script.text
    assert 'action.className = "error-action"' in script.text
    assert 'summary.textContent = "技术详情"' in script.text
    assert 'src="assets/pdf-viewer.js"' in page.text
    assert 'href="assets/style.css"' in page.text
    assert client.get("/assets/pdf-viewer.js").status_code == 200
    assert client.get("/assets/pdfjs/pdf.min.mjs").status_code == 200
    viewer_script = client.get("/assets/pdf-viewer.js").text
    assert 'from "./pdfjs/pdf.min.mjs"' in viewer_script
    assert 'new URL("./pdfjs/pdf.worker.min.mjs", import.meta.url)' in viewer_script
    assert "PDF 加载失败：" in viewer_script
    assert 'disableWorker: true' in viewer_script
    assert 'showNativePdfFallback' in script.text
    assert 'className = "pdf-native-viewer"' in script.text


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
