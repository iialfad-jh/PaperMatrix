from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .retry import error_status_code, is_transient_error


RUN_REPORT_VERSION = 1
FAILED_STATUSES = {"pdf_failed", "llm_failed", "skipped", "cancelled"}


def create_run_report(config: dict, paper_plan: list[tuple[Path, str]]) -> dict:
    report = {
        "report_version": RUN_REPORT_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "config": config,
        "summary": {},
        "items": [
            {
                "paper_id": paper_id,
                "pdf_path": str(pdf_path.resolve()),
                "status": "imported",
                "stages": ["imported"],
                "cache_hit": False,
                "llm_max_retries": config["retries"],
            }
            for pdf_path, paper_id in paper_plan
        ],
    }
    update_run_summary(report)
    return report


def load_run_report(path: str | Path) -> dict:
    input_path = Path(path)
    try:
        with input_path.open("r", encoding="utf-8") as file:
            report = json.load(file)
    except OSError as exc:
        raise ValueError(f"could not read run report: {input_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid run report JSON: {input_path}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("items"), list) or not isinstance(report.get("config"), dict):
        raise ValueError(f"invalid run report structure: {input_path}")
    return report


def save_run_report(report: dict, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = _now()
    update_run_summary(report)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    temporary_path.replace(output_path)
    return output_path


def update_run_summary(report: dict) -> None:
    items = report.get("items", [])
    report["summary"] = {
        "total": len(items),
        "imported": sum("imported" in item.get("stages", []) for item in items),
        "cache_hit": sum(bool(item.get("cache_hit")) for item in items),
        "extracted": sum("extracted" in item.get("stages", []) for item in items),
        "pdf_failed": sum(item.get("status") == "pdf_failed" for item in items),
        "llm_failed": sum(item.get("status") == "llm_failed" for item in items),
        "exported": sum("exported" in item.get("stages", []) for item in items),
        "skipped": sum(item.get("status") == "skipped" for item in items),
        "cancelled": sum(item.get("status") == "cancelled" for item in items),
    }


def record_failure(item: dict, status: str, exc: Exception) -> None:
    item["status"] = status
    item["error"] = {
        "type": exc.__class__.__name__,
        "message": str(exc)[:2000],
        "transient": is_transient_error(exc),
        "status_code": error_status_code(exc),
    }


def failed_items(report: dict) -> list[dict]:
    return [item for item in report.get("items", []) if item.get("status") in FAILED_STATUSES]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
