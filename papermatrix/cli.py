from __future__ import annotations

from pathlib import Path

import typer

from .cache import build_cache_metadata, is_cache_metadata_current, load_cache_metadata, save_cache_metadata
from .chunk import chunk_pages, load_chunks_jsonl, save_chunks_jsonl
from .export import export_evidence, export_matrix, normalize_language
from .extract import extract_paper, load_extract_json, save_extract_json
from .llm import OpenAILLMClient, resolve_openai_config
from .pdf import read_pdf_pages
from .selector import select_chunks_for_extraction


app = typer.Typer(help="Build paper comparison matrices from local PDF folders.")

CLI_MESSAGES = {
    "en": {
        "config": "LLM config: {config}",
        "no_pdfs": "No PDF files found in {papers_dir}",
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
    },
    "zh": {
        "config": "LLM 配置：{config}",
        "no_pdfs": "在 {papers_dir} 中没有找到 PDF 文件",
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
    },
}


def _message(language: str, key: str, **kwargs: object) -> str:
    return CLI_MESSAGES[language][key].format(**kwargs)


@app.command()
def main(
    papers_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True, help="Folder containing PDF papers."),
    out: Path = typer.Option(Path("matrix.md"), "--out", "-o", help="Markdown matrix output path."),
    max_chars: int = typer.Option(3500, help="Maximum characters per chunk."),
    max_chunks: int = typer.Option(12, help="Maximum chunks sent to the LLM per paper."),
    model: str | None = typer.Option(None, help="OpenAI model name. Defaults to PAPERMATRIX_MODEL, OPENAI_MODEL, then gpt-4.1-mini."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible API base URL."),
    api_mode: str | None = typer.Option(None, "--api-mode", help='API mode: "chat" or "responses".'),
    language: str = typer.Option("zh", "--language", "-l", help='Output language: "zh" or "en".'),
    force: bool = typer.Option(False, "--force", help="Ignore cached extracts and rerun PDF extraction plus LLM calls."),
    debug_config: bool = typer.Option(False, "--debug-config", help="Print model/API configuration without revealing the API key."),
    provider_probe: bool = typer.Option(False, "--provider-probe", help="Send one tiny provider test request and exit."),
) -> None:
    try:
        output_language = normalize_language(language)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
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
            )
        return llm_client

    if debug_config:
        typer.echo(_message(output_language, "config", config=get_llm_client().config_summary()))

    if provider_probe:
        _run_provider_probe(get_llm_client(), language=output_language)
        return

    pdf_paths = sorted(papers_dir.glob("*.pdf"))
    if not pdf_paths:
        raise typer.BadParameter(_message(output_language, "no_pdfs", papers_dir=papers_dir))

    work_dir = out.parent / ".papermatrix"
    extracts = []
    chunks_by_paper = {}

    for pdf_path in pdf_paths:
        paper_id = pdf_path.stem
        extract_path = work_dir / f"{paper_id}_extract.json"
        chunks_path = work_dir / f"{paper_id}_chunks.jsonl"
        metadata_path = work_dir / f"{paper_id}_meta.json"
        current_metadata = build_cache_metadata(
            pdf_path,
            language=output_language,
            llm_config=llm_config,
            max_chars=max_chars,
            max_chunks=max_chunks,
        )
        cache_is_current = is_cache_metadata_current(load_cache_metadata(metadata_path), current_metadata)

        if extract_path.exists() and not force and cache_is_current:
            typer.echo(_message(output_language, "using_cache", filename=pdf_path.name))
            extract = load_extract_json(extract_path, paper_id=paper_id)
            if chunks_path.exists():
                chunks_by_paper[extract.paper_id] = load_chunks_jsonl(chunks_path)
            extracts.append(extract)
            continue
        if extract_path.exists() and not force:
            typer.echo(_message(output_language, "cache_stale", filename=pdf_path.name))

        typer.echo(_message(output_language, "processing", filename=pdf_path.name))

        pages = read_pdf_pages(pdf_path)
        chunks = chunk_pages(pages, paper_id=paper_id, max_chars=max_chars)
        save_chunks_jsonl(chunks, chunks_path)

        selected_chunks = select_chunks_for_extraction(chunks, max_chunks=max_chunks)
        try:
            extract = extract_paper(paper_id, selected_chunks, get_llm_client())
        except Exception as exc:
            if _is_provider_error(exc):
                typer.echo(_format_provider_error(exc, language=output_language), err=True)
                raise typer.Exit(1) from exc
            raise
        save_extract_json(extract, extract_path)
        save_cache_metadata(current_metadata, metadata_path)
        chunks_by_paper[extract.paper_id] = chunks
        extracts.append(extract)

    markdown_path, csv_path = export_matrix(extracts, out, language=output_language)
    evidence_path = out.with_suffix(".evidence.md")
    export_evidence(extracts, evidence_path, chunks_by_paper=chunks_by_paper, language=output_language)
    typer.echo(_message(output_language, "wrote", path=markdown_path))
    typer.echo(_message(output_language, "wrote", path=csv_path))
    typer.echo(_message(output_language, "wrote", path=evidence_path))


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
