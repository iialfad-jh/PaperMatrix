from __future__ import annotations

import csv
import hashlib
import json
import threading
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

try:  # Optional dependency: importing papermatrix.web should still give a useful error without it.
    from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:  # pragma: no cover - depends on the caller's installation extras
    FastAPI = None  # type: ignore[assignment]
    File = Form = Header = HTTPException = UploadFile = None  # type: ignore[assignment]
    FileResponse = HTMLResponse = JSONResponse = StreamingResponse = StaticFiles = None  # type: ignore[assignment]

from .batch import load_sources_file, resolve_source_list, save_import_report
from .llm import OpenAILLMClient, resolve_openai_config
from .pipeline import (
    CancellationToken,
    PipelineConfig,
    PipelineError,
    PipelineResult,
    ProgressEvent,
    paper_ids_for_paths,
    resolve_project_dir,
    run_pipeline,
)
from .presets import list_presets, load_preset
from .run_report import failed_items, load_run_report
from .schema import FieldSpec, parse_field_specs


ASSETS_DIR = Path(__file__).with_name("web_assets")
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "cancelling"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


ERROR_GUIDANCE = {
    "api_key_missing": (
        "未检测到 API Key",
        "当前任务没有可用的 API Key。",
        "请在高级设置中填写 API Key，或设置 OPENAI_API_KEY 后重启本地服务。",
    ),
    "api_key_invalid": (
        "API Key 无效或无权限",
        "模型服务拒绝了当前凭据。",
        "请检查 Key 是否完整、未过期，并确认它有权访问当前服务和模型。",
    ),
    "network_unreachable": (
        "无法连接模型服务",
        "本地服务未能与模型 API 建立网络连接。",
        "请检查网络、兼容 API 地址、DNS 和防火墙，然后再次测试连接。",
    ),
    "model_not_found": (
        "模型不存在或无权访问",
        "当前服务找不到所选模型，或当前账号没有访问权限。",
        "请核对模型名称，并确认该模型在当前 API 地址和账号下可用。",
    ),
    "api_mode_incompatible": (
        "API 模式不兼容",
        "当前服务不支持所选 API 模式或请求端点。",
        "请在 Chat Completions 与 Responses 之间切换后重新测试连接。",
    ),
    "rate_or_quota_limit": (
        "请求频率或余额受限",
        "模型服务因限流、额度、余额或计费状态拒绝了请求。",
        "请稍后重试，并检查服务商的用量、余额、额度和计费状态。",
    ),
    "request_timeout": (
        "模型请求超时",
        "模型服务未在限定时间内返回结果。",
        "请重试；若持续发生，请检查 API 地址并减少单次任务规模或文本块数量。",
    ),
    "tls_or_proxy": (
        "TLS 或代理连接失败",
        "HTTPS 证书校验或代理连接阻止了模型请求。",
        "请检查系统时间、代理设置、证书链，以及网络中的 HTTPS 检查软件。",
    ),
    "pdf_processing": (
        "PDF 处理失败",
        "论文文件无法正常读取或解析。",
        "请确认文件是完整、未加密的 PDF；必要时重新下载后再试。",
    ),
    "unknown": (
        "任务执行失败",
        "PaperMatrix 未能完成当前任务。",
        "请查看下方技术详情和运行报告；若是临时服务错误，可重试失败项。",
    ),
}


def _classify_service_error(
    error: Exception | dict[str, Any] | str,
    *,
    secret: str | None = None,
    failure_stage: str | None = None,
) -> dict[str, Any]:
    if isinstance(error, dict):
        error_type = str(error.get("type") or "Error")
        message = str(error.get("message") or "")
        status_code = error.get("status_code")
    elif isinstance(error, Exception):
        error_type = error.__class__.__name__
        message = str(error)
        status_code = getattr(error, "status_code", None)
        if status_code is None:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
    else:
        error_type = "Error"
        message = str(error)
        status_code = None

    combined = f"{error_type} {message}".lower()
    if ("api key" in combined or "api_key" in combined) and any(
        marker in combined for marker in ("must be set", "missing", "not provided", "required")
    ):
        code = "api_key_missing"
    elif status_code in {401, 403} or any(
        marker in combined
        for marker in ("authenticationerror", "permissiondenied", "invalid_api_key", "incorrect api key", "unauthorized")
    ):
        code = "api_key_invalid"
    elif status_code in {402, 429} or any(
        marker in combined
        for marker in (
            "ratelimit",
            "rate limit",
            "insufficient_quota",
            "quota",
            "billing",
            "credit balance",
            "余额",
        )
    ):
        code = "rate_or_quota_limit"
    elif any(
        marker in combined
        for marker in ("model_not_found", "model does not exist", "model not found", "no access to model")
    ) or (status_code == 404 and "model" in combined):
        code = "model_not_found"
    elif status_code in {404, 405} or any(
        marker in combined
        for marker in (
            "unknown url",
            "unsupported endpoint",
            "chat.completions",
            "responses endpoint",
            "api mode",
            "method not allowed",
        )
    ) or ("endpoint" in combined and any(marker in combined for marker in ("not supported", "incompatible"))):
        code = "api_mode_incompatible"
    elif any(
        marker in combined
        for marker in ("ssl", "tls", "certificate verify", "certificate_verify", "proxyerror", "proxy error")
    ):
        code = "tls_or_proxy"
    elif any(marker in combined for marker in ("timeout", "timed out", "apitimeouterror")):
        code = "request_timeout"
    elif any(
        marker in combined
        for marker in (
            "apiconnectionerror",
            "connectionerror",
            "connection refused",
            "connection reset",
            "name resolution",
            "getaddrinfo",
            "network is unreachable",
            "dns",
        )
    ):
        code = "network_unreachable"
    elif failure_stage == "pdf_failed":
        code = "pdf_processing"
    else:
        code = "unknown"

    title, friendly_message, action = ERROR_GUIDANCE[code]
    technical = f"{error_type}: {message}".strip()
    if secret:
        technical = technical.replace(secret, "***")
    return {
        "code": code,
        "title": title,
        "message": friendly_message,
        "action": action,
        "technical": technical[:1200],
        "status_code": status_code,
    }


def _classify_run_failure(report: dict[str, Any], *, secret: str | None = None) -> dict[str, Any]:
    export_error = report.get("export_error")
    if isinstance(export_error, dict):
        return _classify_service_error(export_error, secret=secret)
    failed = []
    for item in report.get("items", []):
        item_error = item.get("error")
        if isinstance(item_error, dict):
            failed.append((item, _classify_service_error(item_error, secret=secret, failure_stage=item.get("status"))))
    if not failed:
        return _classify_service_error("No paper could be exported", secret=secret)

    primary = dict(failed[0][1])
    primary["failure_summary"] = _run_failure_summary(report, failed)
    if primary["failure_summary"]["total"] > 1:
        summary = primary["failure_summary"]
        lead_group = summary["groups"][0] if summary["groups"] else None
        primary["message"] = f"已导出 {summary['exported']}/{summary['total']} 篇论文，{summary['failed']} 篇失败。"
        if lead_group:
            primary["message"] += f" 主要原因：{lead_group['title']}（{lead_group['count']} 篇）。"
    return primary


def _run_failure_summary(report: dict[str, Any], failed: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    items = report.get("items", [])
    grouped: dict[str, dict[str, Any]] = {}
    for index, (item, detail) in enumerate(failed):
        code = str(detail.get("code") or "unknown")
        group = grouped.setdefault(
            code,
            {
                "code": code,
                "title": detail.get("title") or ERROR_GUIDANCE["unknown"][0],
                "count": 0,
                "first_index": index,
                "papers": [],
            },
        )
        group["count"] += 1
        group["papers"].append(
            {
                "paper_id": str(item.get("paper_id") or ""),
                "filename": _failure_item_filename(item),
                "status": str(item.get("status") or ""),
                "technical": str(detail.get("technical") or "")[:500],
            }
        )
    groups = sorted(grouped.values(), key=lambda group: (-int(group["count"]), int(group["first_index"])))
    for group in groups:
        group.pop("first_index", None)
    return {
        "total": int(summary.get("total") or len(items)),
        "exported": int(summary.get("exported") or 0),
        "failed": len(failed),
        "groups": groups,
    }


def _failure_item_filename(item: dict[str, Any]) -> str:
    pdf_path = item.get("pdf_path")
    if isinstance(pdf_path, str) and pdf_path:
        return Path(pdf_path).name
    return str(item.get("paper_id") or "paper")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobSpec:
    project_id: str
    source_lines: tuple[str, ...] = ()
    uploaded_paths: tuple[Path, ...] = ()
    language: str = "zh"
    preset: str | None = "general"
    fields: str | None = None
    model: str | None = None
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    api_mode: str | None = None
    reasoning_effort: str | None = None
    max_chars: int = 3500
    max_chunks: int = 12
    retries: int = 2
    force: bool = False
    fail_fast: bool = False
    retry_report: Path | None = None


@dataclass
class WebJob:
    id: str
    spec: JobSpec
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    latest_progress: dict[str, Any] | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_detail: dict[str, Any] | None = None
    artifacts: dict[str, Path] = field(default_factory=dict)
    run_report_path: Path | None = None
    token: CancellationToken = field(default_factory=CancellationToken, repr=False)
    events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def add_event(self, event_type: str, data: dict[str, Any]) -> None:
        with self.condition:
            event = {"id": len(self.events) + 1, "type": event_type, "data": data}
            self.events.append(event)
            self.condition.notify_all()

    def set_status(
        self,
        status: str,
        *,
        error: str | None = None,
        error_detail: dict[str, Any] | None = None,
    ) -> None:
        with self.condition:
            self.status = status
            if error is not None:
                self.error = error
            if error_detail is not None:
                self.error_detail = error_detail
            if status in TERMINAL_STATUSES:
                self.finished_at = _now()
            snapshot = self.as_dict()
            event = {"id": len(self.events) + 1, "type": "job", "data": snapshot}
            self.events.append(event)
            self.condition.notify_all()

    def on_progress(self, event: ProgressEvent) -> None:
        payload = event.as_dict()
        with self.condition:
            self.latest_progress = payload
            next_event = {"id": len(self.events) + 1, "type": "progress", "data": payload}
            self.events.append(next_event)
            self.condition.notify_all()

    def as_dict(self) -> dict[str, Any]:
        artifacts = {
            name: f"/api/jobs/{self.id}/files/{name}"
            for name, path in self.artifacts.items()
            if path.is_file()
        }
        can_retry = bool(
            self.status in TERMINAL_STATUSES
            and self.run_report_path
            and self.run_report_path.is_file()
            and self._has_failed_items()
        )
        return {
            "id": self.id,
            "project_id": self.spec.project_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latest_progress": self.latest_progress,
            "summary": self.summary,
            "error": self.error,
            "error_detail": self.error_detail,
            "artifacts": artifacts,
            "can_cancel": self.status in ACTIVE_STATUSES,
            "can_retry": can_retry,
        }

    def _has_failed_items(self) -> bool:
        if not self.run_report_path:
            return False
        try:
            return bool(failed_items(load_run_report(self.run_report_path)))
        except ValueError:
            return False


class JobConflictError(ValueError):
    pass


class JobManager:
    def __init__(
        self,
        base_dir: str | Path,
        *,
        pipeline_runner: Callable[..., PipelineResult] = run_pipeline,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.workspace_root = self.base_dir / ".papermatrix"
        self.pipeline_runner = pipeline_runner
        self._jobs: dict[str, WebJob] = {}
        self._lock = threading.Lock()

    def project_dir(self, project_id: str) -> Path:
        return resolve_project_dir(self.workspace_root, project_id)

    def is_project_active(self, project_id: str) -> bool:
        with self._lock:
            return any(job.spec.project_id == project_id and job.status in ACTIVE_STATUSES for job in self._jobs.values())

    def submit(self, spec: JobSpec) -> WebJob:
        self.project_dir(spec.project_id)
        with self._lock:
            if any(job.spec.project_id == spec.project_id and job.status in ACTIVE_STATUSES for job in self._jobs.values()):
                raise JobConflictError(f'project "{spec.project_id}" already has an active job')
            job = WebJob(id=uuid.uuid4().hex, spec=spec)
            self._jobs[job.id] = job
        job.add_event("job", job.as_dict())
        thread = threading.Thread(target=self._execute, args=(job,), name=f"papermatrix-{job.id[:8]}", daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> WebJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self) -> list[WebJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def cancel(self, job_id: str) -> WebJob:
        job = self.get(job_id)
        with job.condition:
            if job.status not in ACTIVE_STATUSES:
                raise JobConflictError(f'job "{job_id}" is already {job.status}')
            job.token.cancel()
            job.status = "cancelling"
            event = {"id": len(job.events) + 1, "type": "job", "data": job.as_dict()}
            job.events.append(event)
            job.condition.notify_all()
        return job

    def retry(self, job_id: str) -> WebJob:
        previous = self.get(job_id)
        if previous.status not in TERMINAL_STATUSES:
            raise JobConflictError("only finished jobs can be retried")
        if not previous.run_report_path or not previous.run_report_path.is_file():
            raise JobConflictError("job does not have a run report")
        report = load_run_report(previous.run_report_path)
        if not failed_items(report):
            raise JobConflictError("run report contains no failed papers")
        retry_spec = JobSpec(
            project_id=previous.spec.project_id,
            language=previous.spec.language,
            api_key=previous.spec.api_key,
            retries=previous.spec.retries,
            retry_report=previous.run_report_path,
        )
        return self.submit(retry_spec)

    def iter_events(self, job_id: str, after: int = 0) -> Iterator[str]:
        job = self.get(job_id)
        cursor = max(0, after)
        while True:
            with job.condition:
                pending = [event for event in job.events if event["id"] > cursor]
                if not pending and job.status not in TERMINAL_STATUSES:
                    job.condition.wait(timeout=15)
                    pending = [event for event in job.events if event["id"] > cursor]
                terminal = job.status in TERMINAL_STATUSES
            if pending:
                for event in pending:
                    cursor = int(event["id"])
                    yield _format_sse(event)
                continue
            if terminal:
                return
            yield ": keep-alive\n\n"

    def _execute(self, job: WebJob) -> None:
        job.started_at = _now()
        job.set_status("running")
        try:
            if job.token.is_cancelled():
                job.set_status("cancelled")
                return
            prepared = self._prepare_pipeline(job)
            if job.token.is_cancelled():
                job.set_status("cancelled")
                return
            result = self.pipeline_runner(
                prepared["config"],
                prepared["paper_plan"],
                prepared["llm_factory"],
                retry_state=prepared["retry_state"],
                run_report_path=prepared["run_report_path"],
                progress_callback=job.on_progress,
                cancellation_token=job.token,
            )
            job.run_report_path = result.run_report_path
            job.summary = dict(result.run_report.get("summary", {}))
            for name, path in {
                "markdown": result.markdown_path,
                "csv": result.csv_path,
                "evidence": result.evidence_path,
                "report": result.run_report_path,
            }.items():
                if path is not None:
                    job.artifacts[name] = Path(path)
            import_report_path = prepared["config"].work_dir / "import-report.json"
            if import_report_path.is_file():
                job.artifacts["import_report"] = import_report_path
            if result.cancelled:
                job.set_status("cancelled")
            elif result.success:
                job.set_status("completed")
            else:
                detail = _classify_run_failure(result.run_report, secret=job.spec.api_key)
                job.set_status("failed", error=detail["message"], error_detail=detail)
        except Exception as exc:
            if job.token.is_cancelled():
                job.set_status("cancelled")
            else:
                detail = _classify_service_error(exc, secret=job.spec.api_key)
                job.set_status("failed", error=detail["message"], error_detail=detail)

    def _prepare_pipeline(self, job: WebJob) -> dict[str, Any]:
        spec = job.spec
        if spec.retry_report is not None:
            retry_state = load_run_report(spec.retry_report)
            if not failed_items(retry_state):
                raise PipelineError("run report contains no failed papers")
            stored = retry_state["config"]
            field_specs = tuple(FieldSpec.model_validate(item) for item in stored["fields"])
            language = str(stored["language"])
            retries = int(stored.get("retries", spec.retries))
            llm_config = dict(stored["llm"])
            out = Path(stored["out"])
            work_dir = Path(stored.get("work_dir", out.parent / ".papermatrix"))
            project_id = stored.get("project_id") or spec.project_id
            paper_plan = [
                (Path(item["pdf_path"]), str(item["paper_id"]))
                for item in retry_state["items"]
                if item.get("pdf_path") and item.get("paper_id")
            ]
            preset = stored.get("preset")
            max_chars = int(stored["max_chars"])
            max_chunks = int(stored["max_chunks"])
            force = False
            fail_fast = False
            run_report_path = spec.retry_report
        else:
            retry_state = None
            language = spec.language
            retries = spec.retries
            if spec.preset:
                selected_preset = load_preset(spec.preset)
                field_specs = tuple(selected_preset.fields)
                preset = selected_preset.name
            else:
                field_specs = tuple(parse_field_specs(spec.fields))
                preset = None
            llm_config = resolve_openai_config(
                model=spec.model,
                base_url=spec.base_url,
                api_mode=spec.api_mode,
                reasoning_effort=spec.reasoning_effort,
                language=language,
            )
            project_id = spec.project_id
            work_dir = self.project_dir(project_id)
            work_dir.mkdir(parents=True, exist_ok=True)
            out = work_dir / "matrix.md"
            source_file = work_dir / "job-input-sources.txt"
            all_sources = [str(path.resolve()) for path in spec.uploaded_paths] + list(spec.source_lines)
            source_file.write_text("\n".join(all_sources) + "\n", encoding="utf-8")
            job.on_progress(ProgressEvent("import", "started", total=len(all_sources)))
            entries = load_sources_file(source_file)
            pdf_paths, import_report = resolve_source_list(
                entries,
                work_dir / "downloads",
                sources_file=source_file,
                force=spec.force,
                fail_fast=spec.fail_fast,
                retries=retries,
            )
            save_import_report(import_report, work_dir / "import-report.json")
            job.on_progress(
                ProgressEvent("import", "completed", total=len(all_sources), payload=dict(import_report["summary"]))
            )
            if import_report["stopped_early"]:
                raise PipelineError("source import stopped after the first failure")
            if not pdf_paths:
                raise PipelineError("no PDF files were resolved from the submitted sources")
            paper_plan = list(zip(pdf_paths, paper_ids_for_paths(pdf_paths), strict=True))
            max_chars = spec.max_chars
            max_chunks = spec.max_chunks
            force = spec.force
            fail_fast = spec.fail_fast
            run_report_path = work_dir / "run-report.json"

        if not paper_plan:
            raise PipelineError("run report contains no retryable PDF paths")
        config = PipelineConfig(
            out=out,
            work_dir=work_dir,
            language=language,
            max_chars=max_chars,
            max_chunks=max_chunks,
            field_specs=field_specs,
            llm_config=llm_config,
            retries=retries,
            preset=preset,
            force=force,
            fail_fast=fail_fast,
            project_id=project_id,
        )
        llm_client: OpenAILLMClient | None = None

        def llm_factory() -> OpenAILLMClient:
            nonlocal llm_client
            if llm_client is None:
                llm_client = OpenAILLMClient(
                    model=llm_config["model"],
                    api_key=spec.api_key,
                    base_url=llm_config["base_url"] or None,
                    api_mode=llm_config["api_mode"],
                    reasoning_effort=llm_config.get("reasoning_effort", "auto"),
                    language=language,
                    max_retries=retries,
                )
            return llm_client

        return {
            "config": config,
            "paper_plan": paper_plan,
            "llm_factory": llm_factory,
            "retry_state": retry_state,
            "run_report_path": run_report_path,
        }


def _format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f'id: {event["id"]}\ndata: {data}\n\n'


def _clean_filename(filename: str) -> str:
    cleaned = Path(filename.replace("\\", "/")).name.strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("uploaded file must have a valid filename")
    return cleaned


def _read_preview(job: WebJob) -> dict[str, Any]:
    csv_path = job.artifacts.get("csv")
    if not csv_path or not csv_path.is_file():
        raise FileNotFoundError("matrix preview is not available")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    evidence_path = job.artifacts.get("evidence")
    evidence = evidence_path.read_text(encoding="utf-8") if evidence_path and evidence_path.is_file() else ""
    return {"columns": columns, "rows": rows, "evidence": evidence}


def create_app(base_dir: str | Path | None = None, *, manager: JobManager | None = None):
    if FastAPI is None:  # pragma: no cover - exercised only without the optional dependency
        raise RuntimeError('Web UI dependencies are missing; install them with pip install -e ".[web]"')

    root = Path(base_dir or Path.cwd()).resolve()
    job_manager = manager or JobManager(root)
    app = FastAPI(title="PaperMatrix Web", version="0.1.0")
    app.state.job_manager = job_manager
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((ASSETS_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {
            "presets": [preset.as_dict() for preset in list_presets()],
            "defaults": {
                "language": "zh",
                "preset": "general",
                "model": resolve_openai_config()["model"],
                "api_mode": resolve_openai_config()["api_mode"],
                "reasoning_effort": resolve_openai_config()["reasoning_effort"],
                "max_chars": 3500,
                "max_chunks": 12,
                "retries": 2,
            },
        }

    @app.post("/api/provider-probe")
    def provider_probe(
        language: str = Form("zh"),
        model: str = Form(""),
        api_key: str = Form(""),
        base_url: str = Form(""),
        api_mode: str = Form(""),
        reasoning_effort: str = Form("auto"),
    ):
        submitted_api_key = api_key.strip()
        try:
            llm_config = resolve_openai_config(
                model=model.strip() or None,
                base_url=base_url.strip() or None,
                api_mode=api_mode.strip() or None,
                reasoning_effort=reasoning_effort.strip() or None,
                language=language,
            )
            llm_client = OpenAILLMClient(
                model=llm_config["model"],
                api_key=submitted_api_key or None,
                base_url=llm_config["base_url"] or None,
                api_mode=llm_config["api_mode"],
                reasoning_effort=llm_config["reasoning_effort"],
                language=llm_config["language"],
                max_retries=0,
            )
            llm_client.extract_json(
                "provider-probe",
                [
                    {
                        "chunk_id": "provider-probe_c0",
                        "paper_id": "provider-probe",
                        "pages": [1],
                        "text": "This is a minimal provider connection test for an academic extraction service.",
                    }
                ],
                field_names=["problem"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            error_detail = _classify_service_error(exc, secret=submitted_api_key)
            if error_detail["code"] == "unknown":
                error_detail.update(
                    title="模型服务请求失败",
                    message="连接已建立，但模型服务未能完成测试请求。",
                    action="请核对当前服务商配置，并查看技术详情后重试。",
                )
            return JSONResponse(
                {"detail": error_detail["technical"], "error": error_detail},
                status_code=502,
            )
        return {
            "ok": True,
            "message": "模型服务连接成功，当前配置可以使用。",
            "config": llm_client.config_summary(),
        }

    @app.get("/api/jobs")
    def jobs():
        return {"jobs": [job.as_dict() for job in job_manager.list()]}

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        source: str = Form(""),
        project_id: str = Form(""),
        language: str = Form("zh"),
        preset: str = Form("general"),
        fields: str = Form(""),
        model: str = Form(""),
        api_key: str = Form(""),
        base_url: str = Form(""),
        api_mode: str = Form(""),
        reasoning_effort: str = Form("auto"),
        max_chars: int = Form(3500),
        max_chunks: int = Form(12),
        retries: int = Form(2),
        force: bool = Form(False),
        fail_fast: bool = Form(False),
        files: list[UploadFile] = File(default=[]),
    ):
        normalized_project_id = project_id.strip() or f"review-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        source_lines = tuple(line.strip() for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))
        submitted_files = [upload for upload in files if upload.filename]
        if not source_lines and not submitted_files:
            raise HTTPException(status_code=422, detail="Provide at least one PDF upload or paper source.")
        try:
            project_dir = job_manager.project_dir(normalized_project_id)
            if job_manager.is_project_active(normalized_project_id):
                raise JobConflictError(f'project "{normalized_project_id}" already has an active job')
            if not 1 <= max_chars <= 100_000:
                raise ValueError("max_chars must be between 1 and 100000")
            if not 1 <= max_chunks <= 100:
                raise ValueError("max_chunks must be between 1 and 100")
            if not 0 <= retries <= 10:
                raise ValueError("retries must be between 0 and 10")
            if preset.strip() and fields.strip():
                raise ValueError("preset and custom fields cannot be used together")
            if preset.strip():
                load_preset(preset.strip())
            else:
                parse_field_specs(fields.strip() or None)
            resolve_openai_config(
                model=model.strip() or None,
                base_url=base_url.strip() or None,
                api_mode=api_mode.strip() or None,
                reasoning_effort=reasoning_effort.strip() or None,
                language=language,
            )
        except (ValueError, JobConflictError) as exc:
            status_code = 409 if isinstance(exc, JobConflictError) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        upload_dir = project_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_paths: list[Path] = []
        created_paths: list[Path] = []
        try:
            for upload in submitted_files:
                filename = _clean_filename(upload.filename or "")
                if Path(filename).suffix.lower() != ".pdf":
                    raise ValueError(f"Only PDF uploads are accepted: {filename}")
                temporary_path = upload_dir / f".{uuid.uuid4().hex}.upload"
                size = 0
                digest = hashlib.sha256()
                try:
                    with temporary_path.open("wb") as handle:
                        while chunk := await upload.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_UPLOAD_BYTES:
                                raise ValueError(f"PDF exceeds the 200 MB upload limit: {filename}")
                            digest.update(chunk)
                            handle.write(chunk)
                    destination = upload_dir / f"{digest.hexdigest()[:12]}-{filename}"
                    if destination.exists():
                        temporary_path.unlink()
                    else:
                        temporary_path.replace(destination)
                        created_paths.append(destination)
                    uploaded_paths.append(destination)
                finally:
                    temporary_path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            for upload in files:
                await upload.close()

        spec = JobSpec(
            project_id=normalized_project_id,
            source_lines=source_lines,
            uploaded_paths=tuple(uploaded_paths),
            language=language,
            preset=preset.strip() or None,
            fields=fields.strip() or None,
            model=model.strip() or None,
            api_key=api_key.strip() or None,
            base_url=base_url.strip() or None,
            api_mode=api_mode.strip() or None,
            reasoning_effort=reasoning_effort.strip() or None,
            max_chars=max_chars,
            max_chunks=max_chunks,
            retries=retries,
            force=force,
            fail_fast=fail_fast,
        )
        try:
            job = job_manager.submit(spec)
        except (ValueError, JobConflictError) as exc:
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(job.as_dict(), status_code=202)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return job_manager.get(job_id).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), after: int = 0):
        try:
            cursor = int(last_event_id) if last_event_id else after
            iterator = job_manager.iter_events(job_id, cursor)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        return StreamingResponse(iterator, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            return job_manager.cancel(job_id).as_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except JobConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str):
        try:
            job = job_manager.retry(job_id)
            return JSONResponse(job.as_dict(), status_code=202)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except (ValueError, JobConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/preview")
    def preview(job_id: str):
        try:
            return _read_preview(job_manager.get(job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/files/{artifact}")
    def job_file(job_id: str, artifact: str):
        try:
            job = job_manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        path = job.artifacts.get(artifact)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(path, filename=path.name)

    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    base_dir: str | Path | None = None,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only without the optional dependency
        raise RuntimeError('Web UI dependencies are missing; install them with pip install -e ".[web]"') from exc

    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(base_dir), host=host, port=port, log_level="info")


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
