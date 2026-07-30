from __future__ import annotations

import json
from pathlib import Path

import typer

from .batch import load_sources_file, resolve_source_list, save_import_report
from .export import normalize_language
from .extract import extract_paper
from .llm import OpenAILLMClient, resolve_openai_config
from .pdf import read_pdf_pages
from .pipeline import (
    PipelineConfig,
    PipelineError,
    ProgressEvent,
    paper_ids_for_paths,
    resolve_project_dir,
    run_pipeline,
)
from .presets import list_presets, load_preset
from .run_report import failed_items, load_run_report
from .schema import FieldSpec, parse_field_specs
from .source import SourceError, resolve_pdf_paths


app = typer.Typer(help="Build paper comparison matrices from local PDFs, arXiv, DOI, or PDF URLs.")

CLI_MESSAGES = {
    "en": {
        "config": "LLM config: {config}",
        "no_pdfs": "No PDF files found for {source}",
        "using_cache": "Using cached extract for {filename}",
        "cache_stale": "Cache metadata changed; rerunning {filename}...",
        "processing": "Processing {filename}...",
        "wrote": "Wrote {path}",
        "probe_succeeded": "Provider probe succeeded.",
        "provider_failed": "Provider request failed",
        "status": "status={status_code}",
        "type": "type={error_type}",
        "code": "code={code}",
        "message": "message={message}",
        "fields": "Fields: {fields}",
        "import_summary": "Import summary: {success} success, {cached} cached, {duplicate} duplicate, {failed} failed, {skipped} skipped; {pdfs} PDFs ready.",
        "source_failed": "Source failed at line {line}: {source} | {error}",
        "fail_fast_stopped": "Stopped after the first source failure because --fail-fast is enabled.",
        "paper_failed": "Paper failed: {filename} | {error}",
        "run_summary": "Run summary: {exported} exported, {cache_hit} cache hits, {pdf_failed} PDF failures, {llm_failed} LLM failures, {skipped} skipped, {cancelled} cancelled.",
    },
    "zh": {
        "config": "LLM 配置：{config}",
        "no_pdfs": "没有找到 PDF 文件：{source}",
        "using_cache": "使用缓存结果：{filename}",
        "cache_stale": "缓存元数据已变化，重新处理 {filename}...",
        "processing": "正在处理 {filename}...",
        "wrote": "已写入 {path}",
        "probe_succeeded": "服务商探针请求成功。",
        "provider_failed": "服务商请求失败",
        "status": "状态码={status_code}",
        "type": "类型={error_type}",
        "code": "代码={code}",
        "message": "消息={message}",
        "fields": "字段：{fields}",
        "import_summary": "导入汇总：成功 {success}，缓存命中 {cached}，重复 {duplicate}，失败 {failed}，跳过 {skipped}；可处理 PDF {pdfs} 篇。",
        "source_failed": "第 {line} 行来源失败：{source} | {error}",
        "fail_fast_stopped": "已启用 --fail-fast，在首个来源失败后停止。",
        "paper_failed": "论文处理失败：{filename} | {error}",
        "run_summary": "运行汇总：导出 {exported}，缓存命中 {cache_hit}，PDF 失败 {pdf_failed}，LLM 失败 {llm_failed}，跳过 {skipped}，取消 {cancelled}。",
    },
}


def _message(language: str, key: str, **kwargs: object) -> str:
    return CLI_MESSAGES[language][key].format(**kwargs)


@app.command()
def main(
    source: str | None = typer.Argument(
        None,
        help="Local PDF file/folder, arXiv ID/URL, DOI, or direct PDF URL.",
    ),
    sources_file: Path | None = typer.Option(
        None,
        "--sources-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Text file containing one local, arXiv, DOI, or PDF URL source per line.",
    ),
    out: Path = typer.Option(Path("matrix.md"), "--out", "-o", help="Markdown matrix output path."),
    max_chars: int = typer.Option(3500, help="Maximum characters per chunk."),
    max_chunks: int = typer.Option(12, help="Maximum chunks sent to the LLM per paper."),
    model: str | None = typer.Option(None, help="OpenAI model name. Defaults to PAPERMATRIX_MODEL, OPENAI_MODEL, then gpt-4.1-mini."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible API base URL."),
    api_mode: str | None = typer.Option(None, "--api-mode", help='API mode: "chat" or "responses".'),
    language: str = typer.Option("zh", "--language", "-l", help='Output language: "zh" or "en".'),
    fields: str | None = typer.Option(None, "--fields", help="Comma-separated fields or a JSON fields file."),
    preset: str | None = typer.Option(None, "--preset", help="Use a built-in extraction field preset."),
    list_presets_flag: bool = typer.Option(False, "--list-presets", help="List built-in field presets and exit."),
    show_preset: str | None = typer.Option(None, "--show-preset", help="Show a preset as JSON and exit."),
    force: bool = typer.Option(False, "--force", help="Ignore cached extracts and rerun PDF extraction plus LLM calls."),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop after the first source or paper failure."),
    retries: int = typer.Option(2, "--retries", min=0, max=10, help="Retries for transient network and LLM API failures."),
    project_id: str | None = typer.Option(None, "--project-id", help="Stable project workspace id under .papermatrix/projects."),
    retry_failed: Path | None = typer.Option(
        None,
        "--retry-failed",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Retry failed papers from a previous run report.",
    ),
    debug_config: bool = typer.Option(False, "--debug-config", help="Print model/API configuration without revealing the API key."),
    provider_probe: bool = typer.Option(False, "--provider-probe", help="Send one tiny provider test request and exit."),
    host: str = typer.Option("127.0.0.1", "--host", help="Web UI host (used only with SOURCE=web)."),
    port: int = typer.Option(8765, "--port", min=1, max=65535, help="Web UI port (used only with SOURCE=web)."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser when starting the Web UI."),
) -> None:
    try:
        output_language = normalize_language(language)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if source == "web":
        if sources_file is not None or retry_failed is not None:
            raise typer.BadParameter("web mode cannot be combined with --sources-file or --retry-failed")
        try:
            from .web import serve

            serve(host=host, port=port, open_browser=not no_open, base_dir=Path.cwd())
        except RuntimeError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        return

    if list_presets_flag:
        for available_preset in list_presets():
            typer.echo(f"{available_preset.name}: {available_preset.description(output_language)}")
        return
    if show_preset:
        try:
            selected_preset = load_preset(show_preset)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--show-preset") from exc
        typer.echo(json.dumps(selected_preset.as_dict(), ensure_ascii=False, indent=2))
        return
    if source is not None and sources_file is not None:
        raise typer.BadParameter("SOURCE and --sources-file cannot be used together")
    if retry_failed is not None and (source is not None or sources_file is not None):
        raise typer.BadParameter("--retry-failed cannot be combined with SOURCE or --sources-file")
    if retry_failed is not None and (fields or preset or force):
        raise typer.BadParameter("--retry-failed reuses the report fields and cannot be combined with --fields, --preset, or --force")
    if retry_failed is not None and project_id is not None:
        raise typer.BadParameter("--retry-failed reuses the report project and cannot be combined with --project-id")
    if fields and preset:
        raise typer.BadParameter("--fields and --preset cannot be used together")

    retry_state: dict | None = None
    active_preset_name: str | None = None
    if retry_failed is not None:
        try:
            retry_state = load_run_report(retry_failed)
            stored_config = retry_state["config"]
            output_language = normalize_language(stored_config["language"])
            out = Path(stored_config["out"])
            max_chars = int(stored_config["max_chars"])
            max_chunks = int(stored_config["max_chunks"])
            active_preset_name = stored_config.get("preset")
            field_specs = [FieldSpec.model_validate(field) for field in stored_config["fields"]]
            field_names = [field_spec.name for field_spec in field_specs]
            llm_config = dict(stored_config["llm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise typer.BadParameter(str(exc), param_hint="--retry-failed") from exc
    else:
        try:
            if preset:
                selected_preset = load_preset(preset)
                active_preset_name = selected_preset.name
                field_specs = selected_preset.fields
            else:
                field_specs = parse_field_specs(fields)
            field_names = [field_spec.name for field_spec in field_specs]
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--preset" if preset else "--fields") from exc
        try:
            llm_config = resolve_openai_config(model=model, base_url=base_url, api_mode=api_mode, language=output_language)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    llm_client: OpenAILLMClient | None = None

    def get_llm_client() -> OpenAILLMClient:
        nonlocal llm_client
        if llm_client is None:
            llm_client = OpenAILLMClient(
                model=llm_config["model"],
                base_url=llm_config["base_url"] or None,
                api_mode=llm_config["api_mode"],
                language=output_language,
                max_retries=retries,
            )
        return llm_client

    if debug_config:
        typer.echo(_message(output_language, "config", config=get_llm_client().config_summary()))
        typer.echo(_message(output_language, "fields", fields=", ".join(field_names)))

    if provider_probe:
        _run_provider_probe(get_llm_client(), language=output_language)
        return
    if source is None and sources_file is None and retry_failed is None:
        raise typer.BadParameter(
            "SOURCE, --sources-file, or --retry-failed is required unless an information command is used",
            param_hint="SOURCE/--sources-file/--retry-failed",
        )

    if retry_state is not None:
        if not failed_items(retry_state):
            raise typer.BadParameter("run report contains no failed papers", param_hint="--retry-failed")
        stored_config = retry_state["config"]
        work_dir = Path(stored_config.get("work_dir", out.parent / ".papermatrix"))
        project_id = stored_config.get("project_id")
        paper_plan = [
            (Path(item["pdf_path"]), str(item["paper_id"]))
            for item in retry_state["items"]
            if item.get("pdf_path") and item.get("paper_id")
        ]
        run_report_path = retry_failed
    else:
        work_dir = resolve_project_dir(out.parent / ".papermatrix", project_id)
        if sources_file is not None:
            try:
                source_entries = load_sources_file(sources_file)
            except ValueError as exc:
                raise typer.BadParameter(str(exc), param_hint="--sources-file") from exc
            pdf_paths, import_report = resolve_source_list(
                source_entries,
                work_dir / "downloads",
                sources_file=sources_file,
                force=force,
                fail_fast=fail_fast,
                retries=retries,
            )
            import_report_path = save_import_report(import_report, work_dir / "import-report.json")
            for item in import_report["items"]:
                if item["status"] == "failed":
                    typer.echo(
                        _message(
                            output_language,
                            "source_failed",
                            line=item["line"],
                            source=item["source"],
                            error=item["error"],
                        ),
                        err=True,
                    )
            typer.echo(_message(output_language, "import_summary", **import_report["summary"]))
            typer.echo(_message(output_language, "wrote", path=import_report_path))
            if import_report["stopped_early"]:
                typer.echo(_message(output_language, "fail_fast_stopped"), err=True)
                raise typer.Exit(1)
        else:
            try:
                pdf_paths = resolve_pdf_paths(source, work_dir / "downloads", force=force, retries=retries)
            except SourceError as exc:
                raise typer.BadParameter(str(exc)) from exc
        if not pdf_paths:
            source_description = sources_file if sources_file is not None else source
            typer.echo(_message(output_language, "no_pdfs", source=source_description), err=True)
            raise typer.Exit(1)
        paper_ids = paper_ids_for_paths(pdf_paths)
        paper_plan = list(zip(pdf_paths, paper_ids, strict=True))
        run_report_path = work_dir / "run-report.json"

    if not paper_plan:
        raise typer.BadParameter("run report contains no retryable PDF paths", param_hint="--retry-failed")

    try:
        pipeline_config = PipelineConfig(
            out=out,
            work_dir=work_dir,
            language=output_language,
            max_chars=max_chars,
            max_chunks=max_chunks,
            field_specs=tuple(field_specs),
            llm_config=llm_config,
            retries=retries,
            preset=active_preset_name,
            force=force,
            fail_fast=fail_fast,
            project_id=project_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    def progress(event: ProgressEvent) -> None:
        _echo_progress(output_language, event)

    try:
        result = run_pipeline(
            pipeline_config,
            paper_plan,
            get_llm_client,
            retry_state=retry_state,
            run_report_path=run_report_path,
            progress_callback=progress,
            read_pdf_pages_fn=read_pdf_pages,
            extract_paper_fn=extract_paper,
        )
    except PipelineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    if result.markdown_path:
        typer.echo(_message(output_language, "wrote", path=result.markdown_path))
    if result.csv_path:
        typer.echo(_message(output_language, "wrote", path=result.csv_path))
    if result.evidence_path:
        typer.echo(_message(output_language, "wrote", path=result.evidence_path))
    typer.echo(_message(output_language, "wrote", path=result.run_report_path))
    typer.echo(_message(output_language, "run_summary", **result.run_report["summary"]))
    if not result.success:
        raise typer.Exit(1)


def _paper_ids_for_paths(pdf_paths: list[Path]) -> list[str]:
    """Backward-compatible alias for callers of the former CLI helper."""
    return paper_ids_for_paths(pdf_paths)


def _echo_progress(language: str, event: ProgressEvent) -> None:
    if event.status == "cache_hit" and event.filename:
        typer.echo(_message(language, "using_cache", filename=event.filename))
    elif event.phase == "cache" and event.status == "stale" and event.filename:
        typer.echo(_message(language, "cache_stale", filename=event.filename))
    elif event.phase == "pdf" and event.status == "started" and event.filename:
        typer.echo(_message(language, "processing", filename=event.filename))
    elif event.phase == "paper" and event.status == "failed" and event.filename:
        typer.echo(_message(language, "paper_failed", filename=event.filename, error=event.message), err=True)


def _is_provider_error(exc: Exception) -> bool:
    return hasattr(exc, "status_code") or exc.__class__.__module__.startswith("openai")


def _run_provider_probe(llm_client: OpenAILLMClient, language: str = "zh") -> None:
    chunks = [
        {
            "chunk_id": "probe_c0",
            "paper_id": "probe",
            "pages": [1],
            "text": "This paper proposes a small test method and reports a small benchmark result.",
        }
    ]
    try:
        llm_client.extract_json("probe", chunks)
    except Exception as exc:
        if _is_provider_error(exc):
            typer.echo(_format_provider_error(exc, language=language), err=True)
            raise typer.Exit(1) from exc
        raise
    typer.echo(_message(language, "probe_succeeded"))


def _format_provider_error(exc: Exception, language: str = "zh") -> str:
    language = normalize_language(language)
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or str(exc)
        error_type = error.get("type") or exc.__class__.__name__
        code = error.get("code")
    else:
        message = str(exc)
        error_type = exc.__class__.__name__
        code = None

    parts = [_message(language, "provider_failed")]
    if status_code:
        parts.append(_message(language, "status", status_code=status_code))
    parts.append(_message(language, "type", error_type=error_type))
    if code:
        parts.append(_message(language, "code", code=code))
    parts.append(_message(language, "message", message=message))
    return " | ".join(parts)


if __name__ == "__main__":
    app()
