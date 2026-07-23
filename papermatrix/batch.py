from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .source import SourceError, canonical_source_key, redact_source, resolve_pdf_paths, source_type


IMPORT_REPORT_VERSION = 1


def load_sources_file(path: str | Path) -> list[dict]:
    input_path = Path(path)
    try:
        lines = input_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ValueError(f"could not read sources file: {input_path}") from exc

    entries = []
    for line_number, line in enumerate(lines, start=1):
        raw_source = line.strip()
        if not raw_source or raw_source.startswith("#"):
            continue
        resolved_source = _resolve_relative_local_source(raw_source, input_path.parent)
        entries.append(
            {
                "line": line_number,
                "source": raw_source,
                "resolved_source": resolved_source,
            }
        )
    if not entries:
        raise ValueError(f"sources file contains no sources: {input_path}")
    return entries


def resolve_source_list(
    entries: list[dict],
    download_dir: str | Path,
    *,
    sources_file: str | Path,
    force: bool = False,
    fail_fast: bool = False,
) -> tuple[list[Path], dict]:
    download_path = Path(download_dir)
    preexisting_downloads = {path.resolve() for path in download_path.glob("*.pdf")}
    resolved_pdf_paths: list[Path] = []
    seen_pdf_paths: dict[Path, int] = {}
    seen_sources: dict[str, int] = {}
    items = []
    stopped_early = False

    for index, entry in enumerate(entries):
        raw_source = str(entry["source"])
        resolved_source = str(entry["resolved_source"])
        canonical = canonical_source_key(resolved_source)
        kind = source_type(resolved_source)
        base_item = {
            "line": int(entry["line"]),
            "source": redact_source(raw_source),
            "canonical_source": _redact_canonical_source(canonical),
            "source_type": kind,
        }
        if canonical in seen_sources:
            items.append(
                {
                    **base_item,
                    "status": "duplicate",
                    "duplicate_of_line": seen_sources[canonical],
                    "pdf_paths": [],
                }
            )
            continue
        seen_sources[canonical] = int(entry["line"])

        try:
            paths = resolve_pdf_paths(resolved_source, download_path, force=force)
            if not paths:
                raise SourceError(f"No PDF files found for source: {raw_source}")
            unique_paths = []
            duplicate_of_lines = []
            for path in paths:
                normalized_path = path.resolve()
                if normalized_path in seen_pdf_paths:
                    duplicate_of_lines.append(seen_pdf_paths[normalized_path])
                    continue
                seen_pdf_paths[normalized_path] = int(entry["line"])
                unique_paths.append(path)
                resolved_pdf_paths.append(path)

            if not unique_paths:
                items.append(
                    {
                        **base_item,
                        "status": "duplicate",
                        "duplicate_of_line": duplicate_of_lines[0] if duplicate_of_lines else None,
                        "pdf_paths": [],
                    }
                )
                continue

            is_cached = (
                kind != "local"
                and not force
                and all(path.resolve() in preexisting_downloads for path in unique_paths)
            )
            items.append(
                {
                    **base_item,
                    "status": "cached" if is_cached else "success",
                    "pdf_paths": [str(path) for path in unique_paths],
                }
            )
            preexisting_downloads.update(path.resolve() for path in unique_paths if kind != "local")
        except SourceError as exc:
            items.append({**base_item, "status": "failed", "error": str(exc), "pdf_paths": []})
            if fail_fast:
                stopped_early = True
                for skipped_entry in entries[index + 1 :]:
                    skipped_source = str(skipped_entry["resolved_source"])
                    items.append(
                        {
                            "line": int(skipped_entry["line"]),
                            "source": redact_source(str(skipped_entry["source"])),
                            "canonical_source": _redact_canonical_source(canonical_source_key(skipped_source)),
                            "source_type": source_type(skipped_source),
                            "status": "skipped",
                            "pdf_paths": [],
                        }
                    )
                break

    summary = {
        "total": len(items),
        "success": sum(item["status"] == "success" for item in items),
        "cached": sum(item["status"] == "cached" for item in items),
        "duplicate": sum(item["status"] == "duplicate" for item in items),
        "failed": sum(item["status"] == "failed" for item in items),
        "skipped": sum(item["status"] == "skipped" for item in items),
        "pdfs": len(resolved_pdf_paths),
    }
    report = {
        "report_version": IMPORT_REPORT_VERSION,
        "sources_file": str(Path(sources_file).resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "force": force,
        "fail_fast": fail_fast,
        "stopped_early": stopped_early,
        "summary": summary,
        "items": items,
    }
    return resolved_pdf_paths, report


def save_import_report(report: dict, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return output_path


def _resolve_relative_local_source(source: str, base_dir: Path) -> str:
    if source_type(source) != "local":
        return source
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path)


def _redact_canonical_source(canonical_source: str) -> str:
    if not canonical_source.startswith("url:"):
        return canonical_source
    return f"url:{redact_source(canonical_source[4:])}"
