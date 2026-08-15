# PaperMatrix

Language: [中文](README.md) | English

PaperMatrix turns local PDFs, arXiv references, DOIs, and public PDF URLs into verifiable paper comparison matrices. It exports Markdown, CSV, and page-linked evidence so you can compare papers and check each extracted claim.

Python 3.11 or newer is required.

## Install

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[web]"
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[web]"
```

For the CLI only:

```bash
python -m pip install -e .
```

## Configure an API Key

```bash
export OPENAI_API_KEY="your_api_key_here"
```

For Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

For an OpenAI-compatible provider, set `OPENAI_BASE_URL`, `OPENAI_API_MODE`, and `PAPERMATRIX_MODEL` as needed, or pass the equivalent command-line options.

## Use

### Web Workspace

```bash
papermatrix web
```

Open <http://127.0.0.1:8765>, then upload PDFs or enter one arXiv reference, DOI, PDF URL, or local path per line. The workspace supports field presets, live progress, failed-job retry, PDF evidence review, and matrix preview.

Each job writes its Markdown, CSV, evidence, and reports to a project subdirectory in the selected results folder. The default is `PaperMatrix Results` under the launch directory. Change it in the page to scan another local folder and reopen its historical Markdown results.

### Command Line

Build a matrix from PDFs in a directory:

```bash
papermatrix ./papers --out matrix.md
```

You can also use remote sources:

```bash
papermatrix arxiv:2401.12345 --out matrix.md
papermatrix doi:10.1234/example --out matrix.md
papermatrix https://example.org/paper.pdf --out matrix.md
```

Common options:

```bash
# English output
papermatrix ./papers --out matrix.md --language en

# A built-in field preset
papermatrix ./papers --out matrix.md --preset machine-learning

# Mixed sources: one PDF, arXiv reference, DOI, or URL per line
papermatrix --sources-file sources.txt --out matrix.md

# Ignore cache and extract again
papermatrix ./papers --out matrix.md --force
```

Run `papermatrix --list-presets` to see available presets. Remote downloads, extraction cache, and run reports are stored in `.papermatrix/` by default.

## Output

- `matrix.md`: paper comparison matrix
- `matrix.csv`: matrix for spreadsheet tools
- `matrix.evidence.md`: extracted values with pages, chunks, and source evidence

## Current Limits

- The Web workspace is local and single-user.
- Scanned PDFs and image-only tables do not have OCR support yet.
- Zotero import and paper-collection chat are not available yet.
