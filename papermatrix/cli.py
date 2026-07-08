from __future__ import annotations

from pathlib import Path

import typer

from .chunk import chunk_pages, save_chunks_jsonl
from .export import export_matrix, normalize_language
from .extract import extract_paper, save_extract_json
from .llm import OpenAILLMClient
from .pdf import read_pdf_pages
from .selector import select_chunks_for_extraction


app = typer.Typer(help="Build paper comparison matrices from local PDF folders.")

CLI_MESSAGES = {
    "en": {
        "config": "LLM config: {config}",
        "no_pdfs": "No PDF files found in {papers_dir}",
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
    model: str = typer.Option("gpt-4.1-mini", help="OpenAI model name."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible API base URL."),
    api_mode: str | None = typer.Option(None, "--api-mode", help='API mode: "chat" or "responses".'),
    language: str = typer.Option("zh", "--language", "-l", help='Output language: "zh" or "en".'),
    debug_config: bool = typer.Option(False, "--debug-config", help="Print model/API configuration without revealing the API key."),
    provider_probe: bool = typer.Option(False, "--provider-probe", help="Send one tiny provider test request and exit."),
) -> None:
    try:
        output_language = normalize_language(language)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    llm_client = OpenAILLMClient(model=model, base_url=base_url, api_mode=api_mode, language=output_language)
    if debug_config:
        typer.echo(_message(output_language, "config", config=llm_client.config_summary()))

    if provider_probe:
        _run_provider_probe(llm_client, language=output_language)
        return

    pdf_paths = sorted(papers_dir.glob("*.pdf"))
    if not pdf_paths:
        raise typer.BadParameter(_message(output_language, "no_pdfs", papers_dir=papers_dir))

    work_dir = out.parent / ".papermatrix"
    extracts = []

    for pdf_path in pdf_paths:
        paper_id = pdf_path.stem
        typer.echo(_message(output_language, "processing", filename=pdf_path.name))

        pages = read_pdf_pages(pdf_path)
        chunks = chunk_pages(pages, paper_id=paper_id, max_chars=max_chars)
        save_chunks_jsonl(chunks, work_dir / f"{paper_id}_chunks.jsonl")

        selected_chunks = select_chunks_for_extraction(chunks, max_chunks=max_chunks)
        try:
            extract = extract_paper(paper_id, selected_chunks, llm_client)
        except Exception as exc:
            if _is_provider_error(exc):
                typer.echo(_format_provider_error(exc, language=output_language), err=True)
                raise typer.Exit(1) from exc
            raise
        save_extract_json(extract, work_dir / f"{paper_id}_extract.json")
        extracts.append(extract)

    markdown_path, csv_path = export_matrix(extracts, out, language=output_language)
    typer.echo(_message(output_language, "wrote", path=markdown_path))
    typer.echo(_message(output_language, "wrote", path=csv_path))


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
