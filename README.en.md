# PaperMatrix

Language: [中文](README.md) | English

PaperMatrix is a lightweight Python CLI for turning local PDFs, arXiv papers, or direct PDF URLs into a comparison matrix. It reads PDFs, cleans and chunks paper text, selects extraction-relevant chunks, asks an LLM for structured fields, and exports Markdown, CSV, and evidence files. It supports Windows, macOS, and Linux and requires Python 3.11 or newer.

## Install

A virtual environment is tied to its operating system and cannot be copied between Windows and macOS/Linux. Create `.venv` on the system where you will run PaperMatrix.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[web]"
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[web]"
```

If you only need the CLI, omit the optional Web dependencies:

```bash
python -m pip install -e .
```

## API Key

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

macOS/Linux:

```bash
export OPENAI_API_KEY="your_api_key_here"
```

For an OpenAI-compatible relay or proxy API, also set the base URL and API mode:

```powershell
$env:OPENAI_API_KEY="your_relay_api_key_here"
$env:OPENAI_BASE_URL="https://api.dwai.cloud/v1"
$env:OPENAI_API_MODE="responses"
$env:PAPERMATRIX_MODEL="gpt-5.5"
$env:PAPERMATRIX_REASONING_EFFORT="medium"
```

On macOS/Linux, use the same variable names and replace PowerShell's `$env:NAME="value"` syntax with `export NAME="value"`.

You can also pass them per run:

```powershell
papermatrix ./papers --out matrix.md --model gpt-5.5 --base-url https://api.dwai.cloud/v1 --api-mode responses --reasoning-effort medium
```

Reasoning effort accepts `auto`, `low`, `medium`, or `high`. `auto` leaves the setting to the model or provider; start with `low` or `medium` for structured paper extraction.

## Usage

### Local Web UI

Start the browser workspace:

```bash
papermatrix web
```

The service listens only on `http://127.0.0.1:8765` by default. The page accepts multiple PDF uploads or one local path, arXiv reference, DOI, or PDF URL per line. It provides language and field-preset controls, structured live progress, cancellation, failed-item retry, preview, and downloads for Markdown, CSV, evidence, and the run report. Each job writes its Markdown, CSV, evidence, and reports to a project subdirectory in the selected results folder. The default is `PaperMatrix Results` under the launch directory, and the page can use any local folder instead. The workbench scans Markdown files in that folder, so historical results remain available after a server restart. The advanced-settings connection test validates the current model configuration before any paper upload. Connection and job failures are classified into API key, network, model, API mode, rate/quota, timeout, and TLS/proxy problems, with an action and technical details shown directly in the page. The page restores the most recently used run options from browser storage. An API key can be entered per job, left blank to use `OPENAI_API_KEY`, or explicitly remembered in browser-local storage. Keys are never written to job reports, project caches, or Git.

To avoid opening the system browser or to use a different port:

```bash
papermatrix web --no-open --port 9000
```

### Command line

The default output language is Chinese:

```bash
papermatrix ./papers --out matrix.md
```

You can also pass an arXiv ID, an arXiv page URL, or a direct PDF URL:

```bash
papermatrix arxiv:2401.12345 --out matrix.md
papermatrix https://arxiv.org/abs/2401.12345 --out matrix.md
papermatrix https://example.org/paper.pdf --out matrix.md
papermatrix doi:10.1234/example --out matrix.md
papermatrix https://doi.org/10.1234/example --out matrix.md
```

DOI imports first read Crossref metadata, then try legitimate open PDF links. Set `UNPAYWALL_EMAIL` to also query Unpaywall for open-access repository locations:

```powershell
$env:UNPAYWALL_EMAIL="researcher@example.org"
papermatrix doi:10.1234/example --out matrix.md
```

When no accessible open PDF exists, PaperMatrix reports a clear error and does not save a paywalled page or login page as a PDF. Remote PDFs are cached under `.papermatrix/downloads/`; repeated runs reuse the downloaded file, and `--force` downloads it again and reruns extraction.

For a mixed batch import, use a sources file:

```powershell
papermatrix --sources-file sources.txt --out matrix.md
```

`sources.txt` accepts one source per line, blank lines, and comments beginning with `#`. Relative local paths are resolved from the sources file's directory:

```text
# Local PDFs, arXiv, DOI, and PDF URLs can be mixed
papers/local-paper.pdf
arxiv:2401.12345
doi:10.1234/example
https://example.org/paper.pdf
```

PaperMatrix normalizes and deduplicates arXiv, DOI, URL, and local-path inputs. A failed source does not stop the remaining papers by default; per-source statuses, errors, and cached files are written to `.papermatrix/import-report.json`. To stop at the first failure, use:

```powershell
papermatrix --sources-file sources.txt --out matrix.md --fail-fast
```

Paper processing is isolated too: a damaged PDF or failed LLM request is recorded while the remaining papers continue. Transient download, metadata, and LLM API failures are retried twice by default; permanent request errors are not retried. Change the limit with `--retries`:

```powershell
papermatrix --sources-file sources.txt --out matrix.md --retries 4
```

Every processing run writes `.papermatrix/run-report.json` with each paper's status, completed stages, retry limit, and error summary. Retry only `pdf_failed`, `llm_failed`, `skipped`, or `cancelled` papers while reusing the successful extracts and the original run configuration:

```powershell
papermatrix --retry-failed .papermatrix/run-report.json
```

`--retry-failed` covers papers that already have a resolved local PDF path. Source-import failures remain in `import-report.json`; rerun the original `--sources-file` command to retry those sources while downloaded files remain cached.

Use a stable project id to isolate caches, downloads, extracts, and run reports for recurring work:

```powershell
papermatrix ./papers --out matrix.md --project-id literature-review-2026
```

The workspace is stored under `.papermatrix/projects/literature-review-2026/`. The default command without `--project-id` continues to use `.papermatrix/`. A retry command reads the workspace from its run report, so `--retry-failed` and `--project-id` are intentionally not combined.

For English matrix output:

```bash
papermatrix ./papers --out matrix.md --language en
```

To customize matrix columns, pass comma-separated field names:

```bash
papermatrix ./papers --out matrix.md --fields problem,method,input,output,dataset,result
```

You can also use a built-in field preset:

```powershell
papermatrix ./papers --out matrix.md --preset general
papermatrix ./papers --out matrix.md --preset machine-learning
papermatrix ./papers --out matrix.md --preset plant-growth
papermatrix ./papers --out matrix.md --preset survey
```

List presets or inspect a preset's complete JSON configuration without providing a paper source:

```powershell
papermatrix --list-presets
papermatrix --show-preset plant-growth
```

`general` fits typical experimental papers, `machine-learning` adds model inputs, outputs, and baselines, `plant-growth` adds crop, growth-stage, treatment, and environment fields, and `survey` focuses on review scope, taxonomy, and research gaps. `--preset` cannot be combined with `--fields`; use the output from `--show-preset` as a starting point for a custom fields JSON file.

Field names are used as internal JSON keys, so use English letters, numbers, and underscores, such as `model_input`, `crop_species`, and `future_output`. The default fields remain `problem,method,dataset,metric,result,limitation`.

## Pipeline API

The CLI delegates paper processing to the UI-independent engine in `papermatrix.pipeline`. A Python frontend can build a `PipelineConfig`, call `run_pipeline(...)`, and receive a `PipelineResult` containing output paths and the complete run report.

Pass a callback to `progress_callback` to receive structured `ProgressEvent` values for run, PDF, LLM, paper, cache, and export stages. Pass a `CancellationToken` to stop safely between stages; completed extracts remain reusable, pending papers are recorded as `cancelled`, and they can be resumed with `--retry-failed`. Exceptions raised by a disconnected progress listener do not abort the processing task.

For clearer labels, field descriptions, and chunk-selection keywords, pass a JSON config file:

```powershell
papermatrix ./papers --out matrix.md --fields fields.json
```

```json
{
  "fields": [
    {
      "name": "crop_species",
      "label_zh": "作物/物种",
      "label_en": "Crop/Species",
      "description": "Extract the crop or plant species studied in the paper.",
      "keywords": ["crop", "species", "maize", "arabidopsis"]
    },
    {
      "name": "model_input",
      "label_zh": "模型输入",
      "label_en": "Model Input",
      "description": "Extract what inputs the model uses, such as images, time, weather, or treatment conditions.",
      "keywords": ["input", "condition", "image", "time", "treatment"]
    }
  ]
}
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
matrix.evidence.md
.papermatrix/
  import-report.json
  run-report.json
  downloads/
    arxiv-2401.12345.pdf
    arxiv-2401.12345.source.json
    doi-a-paper-xxxxxxxxxxxx.pdf
    doi-a-paper-xxxxxxxxxxxx.source.json
  paper1_chunks.jsonl
  paper1_extract.json
  paper1_meta.json
```

`matrix.evidence.md` lists each non-unknown field value, evidence pages, chunk id, and the most relevant local source sentences or table rows so you can quickly check whether the LLM extracted the right information.

PaperMatrix detects ruled PDF tables first and falls back to text-based table detection for borderless layouts. Tables are stored as structured `table` chunks with headers, rows, bounding boxes, and page numbers. Matching first/last tables on adjacent pages are merged when their headers match, and large tables are split only between complete rows. Table chunks receive extra relevance for dataset, metric, result, and similarly named custom fields. If table detection fails, normal page-text extraction continues.

On repeated runs, PaperMatrix reuses existing `.papermatrix/*_extract.json` and `.papermatrix/*_meta.json` files when the metadata still matches, then skips PDF reading, chunking, and LLM calls for those papers. Metadata checks the PDF name, size, modification time, output language, model, API mode, base URL, `--max-chars`, `--max-chunks`, preset name, and complete extraction field configuration:

```bash
papermatrix ./papers --out matrix.md
```

The table-aware release raises the cache format version, so extracts created by older versions are rebuilt once and then cached normally.

To ignore cached extracts and rerun extraction:

```bash
papermatrix ./papers --out matrix.md --force
```

The default test suite is fully offline. Real-service checks are opt-in:

Windows PowerShell:

```powershell
$env:PAPERMATRIX_RUN_INTEGRATION="1"
python -m pytest -m integration
```

macOS/Linux:

```bash
PAPERMATRIX_RUN_INTEGRATION=1 python -m pytest -m integration
```

The arXiv download check runs with that flag. The tiny LLM check additionally requires `PAPERMATRIX_RUN_LLM_INTEGRATION=1` and `OPENAI_API_KEY`.

## Output Language

`--language` controls the final Markdown/CSV column names, unknown labels, and page markers:

- `zh`: default, uses Chinese headers such as `论文`, `研究问题`, and `方法`.
- `en`: uses English headers such as `Paper`, `Problem`, and `Method`.

In Chinese mode, the LLM is instructed to summarize extracted field values in Simplified Chinese when possible. Dataset names, metric names, model names, and other proper nouns may remain in their original form. Internal JSON still uses stable English keys for downstream processing.

## Current Limits

- The Web UI is currently local and single-user. Its session list is not restored after a server restart, although project files and run reports remain under `.papermatrix/projects/`.
- No Zotero or chat QA.
- Scanned or image-only tables require OCR and are not recognized yet.
- Extraction only uses selected chunks from each paper.
- Fields without explicit evidence are normalized to `unknown`; Chinese matrix output displays them as `未知`.
