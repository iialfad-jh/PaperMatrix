from __future__ import annotations

from pathlib import Path

import typer

from .chunk import chunk_pages, save_chunks_jsonl
from .export import export_matrix
from .extract import extract_paper, save_extract_json
from .llm import OpenAILLMClient
from .pdf import read_pdf_pages
from .selector import select_chunks_for_extraction


app = typer.Typer(help="Build paper comparison matrices from local PDF folders.")


@app.command()
def main(
    papers_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True, help="Folder containing PDF papers."),
    out: Path = typer.Option(Path("matrix.md"), "--out", "-o", help="Markdown matrix output path."),
    max_chars: int = typer.Option(3500, help="Maximum characters per chunk."),
    max_chunks: int = typer.Option(12, help="Maximum chunks sent to the LLM per paper."),
    model: str = typer.Option("gpt-4.1-mini", help="OpenAI model name."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible API base URL."),
    api_mode: str | None = typer.Option(None, "--api-mode", help='API mode: "chat" or "responses".'),
    debug_config: bool = typer.Option(False, "--debug-config", help="Print model/API configuration without revealing the API key."),
    provider_probe: bool = typer.Option(False, "--provider-probe", help="Send one tiny provider test request and exit."),
) -> None:
    llm_client = OpenAILLMClient(model=model, base_url=base_url, api_mode=api_mode)
    if debug_config:
        typer.echo(f"LLM config: {llm_client.config_summary()}")

    if provider_probe:
        _run_provider_probe(llm_client)
        return

    pdf_paths = sorted(papers_dir.glob("*.pdf"))
    if not pdf_paths:
        raise typer.BadParameter(f"No PDF files found in {papers_dir}")

    work_dir = out.parent / ".papermatrix"
    extracts = []

    for pdf_path in pdf_paths:
        paper_id = pdf_path.stem
        typer.echo(f"Processing {pdf_path.name}...")

        pages = read_pdf_pages(pdf_path)
        chunks = chunk_pages(pages, paper_id=paper_id, max_chars=max_chars)
        save_chunks_jsonl(chunks, work_dir / f"{paper_id}_chunks.jsonl")

        selected_chunks = select_chunks_for_extraction(chunks, max_chunks=max_chunks)
        try:
            extract = extract_paper(paper_id, selected_chunks, llm_client)
        except Exception as exc:
            if _is_provider_error(exc):
                typer.echo(_format_provider_error(exc), err=True)
                raise typer.Exit(1) from exc
            raise
        save_extract_json(extract, work_dir / f"{paper_id}_extract.json")
        extracts.append(extract)

    markdown_path, csv_path = export_matrix(extracts, out)
    typer.echo(f"Wrote {markdown_path}")
    typer.echo(f"Wrote {csv_path}")


def _is_provider_error(exc: Exception) -> bool:
    return hasattr(exc, "status_code") or exc.__class__.__module__.startswith("openai")


def _run_provider_probe(llm_client: OpenAILLMClient) -> None:
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
            typer.echo(_format_provider_error(exc), err=True)
            raise typer.Exit(1) from exc
        raise
    typer.echo("Provider probe succeeded.")


def _format_provider_error(exc: Exception) -> str:
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

    parts = ["Provider request failed"]
    if status_code:
        parts.append(f"status={status_code}")
    parts.append(f"type={error_type}")
    if code:
        parts.append(f"code={code}")
    parts.append(f"message={message}")
    return " | ".join(parts)


if __name__ == "__main__":
    app()
