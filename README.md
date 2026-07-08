# PaperMatrix

PaperMatrix is a minimal Python CLI for turning a local folder of PDF papers into a comparison matrix. It reads PDFs, chunks paper text, selects extraction-relevant chunks, asks an LLM for structured fields, validates the result, and exports Markdown plus CSV.

## Install

Create a virtual environment in the project directory:

```bash
python -m venv .venv
```

Activate it and install the project:

```bash
.venv\Scripts\activate
pip install -e .
```

## OpenAI API Key

Set `OPENAI_API_KEY` before running:

```bash
set OPENAI_API_KEY=your_api_key_here
```

PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

For an OpenAI-compatible relay or proxy API, also set the base URL:

```powershell
$env:OPENAI_API_KEY="your_relay_api_key_here"
$env:OPENAI_BASE_URL="https://api.dwai.cloud/v1"
$env:OPENAI_API_MODE="responses"
```

You can also pass it per run:

```powershell
papermatrix ./papers --out matrix.md --model gpt-5.5 --base-url https://api.dwai.cloud/v1 --api-mode responses
```

## Usage

```bash
papermatrix ./papers --out matrix.md
```

Input:

```text
papers/
  paper1.pdf
  paper2.pdf
```

Output:

```text
matrix.md
matrix.csv
.papermatrix/
  paper1_chunks.jsonl
  paper1_extract.json
```

## Current Limits

- Local PDF folders only.
- No Web UI.
- No arXiv, Zotero, chat QA, or table recognition.
- Extraction only uses selected chunks from each paper.
- Fields without explicit evidence are normalized to `unknown`.
