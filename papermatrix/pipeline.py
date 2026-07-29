from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .cache import build_cache_metadata, is_cache_metadata_current, load_cache_metadata, save_cache_metadata
from .chunk import chunk_pages, load_chunks_jsonl, save_chunks_jsonl
from .export import export_evidence, export_matrix, normalize_language
from .extract import extract_paper, load_extract_json, save_extract_json
from .llm import LLMClient
from .pdf import read_pdf_pages
from .run_report import create_run_report, failed_items, record_failure, save_run_report
from .schema import FieldSpec, PaperExtract, field_specs_metadata
from .selector import select_chunks_for_extraction


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class PipelineError(RuntimeError):
    """A user-facing failure from the pipeline engine."""


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    status: str
    paper_id: str | None = None
    filename: str | None = None
    index: int = 0
    total: int = 0
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "paper_id": self.paper_id,
            "filename": self.filename,
            "index": self.index,
            "total": self.total,
            "message": self.message,
            "payload": self.payload,
            "created_at": self.created_at,
        }


class CancellationToken:
    """Thread-safe cancellation state checked between pipeline stages."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class PipelineConfig:
    out: Path
    work_dir: Path
    language: str
    max_chars: int = 3500
    max_chunks: int = 12
    field_specs: tuple[FieldSpec, ...] = ()
    llm_config: dict[str, str] = field(default_factory=dict)
    retries: int = 2
    preset: str | None = None
    force: bool = False
    fail_fast: bool = False
    project_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "out", Path(self.out))
        object.__setattr__(self, "work_dir", Path(self.work_dir))
        object.__setattr__(self, "field_specs", tuple(self.field_specs))
        object.__setattr__(self, "llm_config", dict(self.llm_config))
        object.__setattr__(self, "language", normalize_language(self.language))
        if self.max_chars <= 0:
            raise ValueError("max_chars must be greater than zero")
        if self.max_chunks <= 0:
            raise ValueError("max_chunks must be greater than zero")
        if not 0 <= self.retries <= 10:
            raise ValueError("retries must be between 0 and 10")
        if not self.field_specs:
            raise ValueError("field_specs must include at least one extraction field")

    @property
    def field_names(self) -> list[str]:
        return [field_spec.name for field_spec in self.field_specs]

    def report_config(self) -> dict[str, Any]:
        return {
            "out": str(self.out.resolve()),
            "work_dir": str(self.work_dir.resolve()),
            "project_id": self.project_id,
            "language": self.language,
            "max_chars": self.max_chars,
            "max_chunks": self.max_chunks,
            "preset": self.preset,
            "fields": field_specs_metadata(list(self.field_specs)),
            "llm": self.llm_config,
            "retries": self.retries,
        }


@dataclass
class PipelineResult:
    success: bool
    cancelled: bool
    extracts: list[PaperExtract]
    run_report: dict
    run_report_path: Path
    markdown_path: Path | None = None
    csv_path: Path | None = None
    evidence_path: Path | None = None


def resolve_project_dir(base_dir: str | Path, project_id: str | None = None) -> Path:
    """Return a stable, traversal-safe workspace for a project."""
    root = Path(base_dir)
    if not project_id:
        return root
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError("project_id must use 1-64 letters, numbers, hyphens, or underscores")
    return root / "projects" / project_id


def run_pipeline(
    config: PipelineConfig,
    paper_plan: list[tuple[Path, str]],
    llm_factory: Callable[[], LLMClient],
    *,
    retry_state: dict | None = None,
    run_report_path: str | Path | None = None,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    read_pdf_pages_fn: Callable[[str | Path], list[dict]] | None = None,
    extract_paper_fn: Callable[..., PaperExtract] | None = None,
) -> PipelineResult:
    """Process papers and export results without depending on Typer or terminal output."""
    _validate_paper_plan(paper_plan)
    config.work_dir.mkdir(parents=True, exist_ok=True)
    token = cancellation_token or CancellationToken()
    read_pages = read_pdf_pages_fn or read_pdf_pages
    extract_from_chunks = extract_paper_fn or extract_paper
    report_path = Path(run_report_path) if run_report_path else config.work_dir / "run-report.json"

    if retry_state is None:
        run_state = create_run_report(config.report_config(), paper_plan)
        retry_targets = {paper_id for _, paper_id in paper_plan}
    else:
        retry_targets = {item["paper_id"] for item in failed_items(retry_state)}
        if not retry_targets:
            raise PipelineError("run report contains no failed papers")
        run_state = retry_state
        run_state.setdefault("config", {}).update(config.report_config())

    save_run_report(run_state, report_path)
    report_items = {str(item["paper_id"]): item for item in run_state["items"] if item.get("paper_id")}
    missing_report_ids = [paper_id for _, paper_id in paper_plan if paper_id not in report_items]
    if missing_report_ids:
        raise PipelineError(f'run report does not contain paper_id "{missing_report_ids[0]}"')
    extracts: list[PaperExtract] = []
    chunks_by_paper: dict[str, list[dict]] = {}
    cancelled = False
    total = len(paper_plan)

    _emit(progress_callback, "run", "started", total=total)

    for plan_index, (pdf_path, paper_id) in enumerate(paper_plan):
        item = report_items[paper_id]
        filename = pdf_path.name
        event_index = plan_index + 1
        if token.is_cancelled():
            cancelled = True
            _mark_cancelled(paper_plan[plan_index:], report_items)
            break

        if retry_state is not None and paper_id not in retry_targets:
            try:
                extract = load_extract_json(
                    config.work_dir / f"{paper_id}_extract.json",
                    paper_id=paper_id,
                    field_names=config.field_names,
                )
                extracts.append(extract)
                chunks_path = config.work_dir / f"{paper_id}_chunks.jsonl"
                if chunks_path.exists():
                    chunks_by_paper[extract.paper_id] = load_chunks_jsonl(chunks_path)
                item["cache_hit"] = True
                _append_stage(item, "cache_hit")
                _emit(progress_callback, "paper", "cache_hit", paper_id, filename, event_index, total)
                continue
            except (OSError, ValueError, json.JSONDecodeError):
                retry_targets.add(paper_id)

        item["status"] = "imported"
        item.pop("error", None)
        _append_stage(item, "imported")
        item["llm_max_retries"] = config.retries
        extract_path = config.work_dir / f"{paper_id}_extract.json"
        chunks_path = config.work_dir / f"{paper_id}_chunks.jsonl"
        metadata_path = config.work_dir / f"{paper_id}_meta.json"

        if not pdf_path.exists():
            _fail_paper(
                item,
                "pdf_failed",
                FileNotFoundError(f"PDF file not found: {pdf_path}"),
                progress_callback,
                paper_id,
                filename,
                event_index,
                total,
            )
            save_run_report(run_state, report_path)
            if config.fail_fast:
                _mark_remaining_skipped(paper_plan[plan_index + 1 :], report_items)
                break
            continue

        try:
            current_metadata = build_cache_metadata(
                pdf_path,
                language=config.language,
                llm_config=config.llm_config,
                max_chars=config.max_chars,
                max_chunks=config.max_chunks,
                fields_metadata=field_specs_metadata(list(config.field_specs)),
                preset=config.preset,
                paper_id=paper_id,
            )
            cache_is_current = is_cache_metadata_current(load_cache_metadata(metadata_path), current_metadata)
        except OSError as exc:
            _fail_paper(item, "pdf_failed", exc, progress_callback, paper_id, filename, event_index, total)
            save_run_report(run_state, report_path)
            if config.fail_fast:
                _mark_remaining_skipped(paper_plan[plan_index + 1 :], report_items)
                break
            continue

        if extract_path.exists() and not config.force and cache_is_current:
            try:
                extract = load_extract_json(extract_path, paper_id=paper_id, field_names=config.field_names)
                if chunks_path.exists():
                    chunks_by_paper[extract.paper_id] = load_chunks_jsonl(chunks_path)
                extracts.append(extract)
                item["status"] = "cache_hit"
                item["cache_hit"] = True
                _append_stage(item, "cache_hit")
                _emit(progress_callback, "paper", "cache_hit", paper_id, filename, event_index, total)
                save_run_report(run_state, report_path)
                continue
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        if extract_path.exists() and not config.force:
            _emit(progress_callback, "cache", "stale", paper_id, filename, event_index, total)

        _emit(progress_callback, "pdf", "started", paper_id, filename, event_index, total)
        try:
            pages = read_pages(pdf_path)
            chunks = chunk_pages(pages, paper_id=paper_id, max_chars=config.max_chars)
            save_chunks_jsonl(chunks, chunks_path)
            table_count = sum(1 for chunk in chunks if chunk.get("kind") == "table")
            _emit(
                progress_callback,
                "pdf",
                "completed",
                paper_id,
                filename,
                event_index,
                total,
                payload={"pages": len(pages), "chunks": len(chunks), "table_chunks": table_count},
            )
        except Exception as exc:
            _fail_paper(item, "pdf_failed", exc, progress_callback, paper_id, filename, event_index, total)
            save_run_report(run_state, report_path)
            if config.fail_fast:
                _mark_remaining_skipped(paper_plan[plan_index + 1 :], report_items)
                break
            continue

        selected_chunks = select_chunks_for_extraction(
            chunks,
            max_chunks=config.max_chunks,
            field_names=config.field_names,
            field_specs=list(config.field_specs),
        )
        if token.is_cancelled():
            cancelled = True
            _mark_cancelled(paper_plan[plan_index:], report_items)
            break

        _emit(
            progress_callback,
            "llm",
            "started",
            paper_id,
            filename,
            event_index,
            total,
            payload={"chunks": len(selected_chunks)},
        )
        try:
            extract = extract_from_chunks(
                paper_id,
                selected_chunks,
                llm_factory(),
                field_names=config.field_names,
                field_specs=list(config.field_specs),
            )
            _emit(progress_callback, "llm", "completed", paper_id, filename, event_index, total)
        except Exception as exc:
            _fail_paper(item, "llm_failed", exc, progress_callback, paper_id, filename, event_index, total)
            save_run_report(run_state, report_path)
            if config.fail_fast:
                _mark_remaining_skipped(paper_plan[plan_index + 1 :], report_items)
                break
            continue

        try:
            save_extract_json(extract, extract_path)
            save_cache_metadata(current_metadata, metadata_path)
        except OSError as exc:
            _fail_paper(item, "pdf_failed", exc, progress_callback, paper_id, filename, event_index, total)
            save_run_report(run_state, report_path)
            if config.fail_fast:
                _mark_remaining_skipped(paper_plan[plan_index + 1 :], report_items)
                break
            continue
        chunks_by_paper[extract.paper_id] = chunks
        extracts.append(extract)
        item["status"] = "extracted"
        item["cache_hit"] = False
        _append_stage(item, "extracted")
        _emit(progress_callback, "paper", "completed", paper_id, filename, event_index, total)
        save_run_report(run_state, report_path)

    save_run_report(run_state, report_path)
    if not extracts:
        _emit(progress_callback, "run", "cancelled" if cancelled else "failed", total=total)
        return PipelineResult(False, cancelled, extracts, run_state, report_path)

    try:
        markdown_path, csv_path = export_matrix(
            extracts,
            config.out,
            language=config.language,
            field_names=config.field_names,
            field_specs=list(config.field_specs),
        )
        evidence_path = config.out.with_suffix(".evidence.md")
        export_evidence(
            extracts,
            evidence_path,
            chunks_by_paper=chunks_by_paper,
            language=config.language,
            field_names=config.field_names,
            field_specs=list(config.field_specs),
        )
    except Exception as exc:
        run_state["export_error"] = {"type": exc.__class__.__name__, "message": str(exc)[:2000]}
        save_run_report(run_state, report_path)
        raise PipelineError(f"could not export pipeline results: {exc}") from exc

    exported_ids = {extract.paper_id for extract in extracts}
    for paper_id in exported_ids:
        item = report_items[paper_id]
        if item.get("status") not in {"pdf_failed", "llm_failed", "skipped", "cancelled"}:
            item["status"] = "exported"
            _append_stage(item, "exported")
    save_run_report(run_state, report_path)
    _emit(progress_callback, "export", "completed", total=total, payload={"papers": len(extracts)})
    _emit(progress_callback, "run", "cancelled" if cancelled else "completed", total=total)
    return PipelineResult(
        not cancelled,
        cancelled,
        extracts,
        run_state,
        report_path,
        markdown_path,
        csv_path,
        evidence_path,
    )


def _emit(
    callback: Callable[[ProgressEvent], None] | None,
    phase: str,
    status: str,
    paper_id: str | None = None,
    filename: str | None = None,
    index: int = 0,
    total: int = 0,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    event = ProgressEvent(phase, status, paper_id, filename, index, total, message, payload or {})
    try:
        callback(event)
    except Exception:
        pass


def _validate_paper_plan(paper_plan: list[tuple[Path, str]]) -> None:
    seen_ids: set[str] = set()
    for _pdf_path, paper_id in paper_plan:
        if (
            not paper_id
            or paper_id in {".", ".."}
            or "/" in paper_id
            or "\\" in paper_id
            or ":" in paper_id
        ):
            raise PipelineError(f'invalid paper_id "{paper_id}"')
        if paper_id in seen_ids:
            raise PipelineError(f'duplicate paper_id "{paper_id}"')
        seen_ids.add(paper_id)


def _fail_paper(
    item: dict,
    status: str,
    exc: Exception,
    callback: Callable[[ProgressEvent], None] | None,
    paper_id: str,
    filename: str,
    index: int,
    total: int,
) -> None:
    record_failure(item, status, exc)
    _emit(callback, "paper", "failed", paper_id, filename, index, total, message=str(exc))


def _append_stage(item: dict, stage: str) -> None:
    stages = item.setdefault("stages", [])
    if stage not in stages:
        stages.append(stage)


def _mark_remaining_skipped(paper_plan: list[tuple[Path, str]], report_items: dict[str, dict]) -> None:
    for _, paper_id in paper_plan:
        item = report_items[paper_id]
        if item.get("status") not in {"exported", "cache_hit", "extracted", "pdf_failed", "llm_failed", "cancelled"}:
            item["status"] = "skipped"


def _mark_cancelled(paper_plan: list[tuple[Path, str]], report_items: dict[str, dict]) -> None:
    for _, paper_id in paper_plan:
        item = report_items[paper_id]
        if item.get("status") not in {"exported", "cache_hit", "extracted", "pdf_failed", "llm_failed"}:
            item["status"] = "cancelled"
            _append_stage(item, "cancelled")
