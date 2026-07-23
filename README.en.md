# PaperMatrix

Language: [中文](README.md) | English

PaperMatrix is a lightweight Python CLI for turning local PDFs, arXiv papers, or direct PDF URLs into a comparison matrix. It reads PDFs, cleans and chunks paper text, selects extraction-relevant chunks, asks an LLM for structured fields, and exports Markdown, CSV, and evidence files.

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

## API Key

Set `OPENAI_API_KEY` before running:

```bash
set OPENAI_API_KEY=your_api_key_here
```

PowerShell:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

For an OpenAI-compatible relay or proxy API, also set the base URL and API mode:

```powershell
$env:OPENAI_API_KEY="your_relay_api_key_here"
$env:OPENAI_BASE_URL="https://api.dwai.cloud/v1"
$env:OPENAI_API_MODE="responses"
$env:PAPERMATRIX_MODEL="gpt-5.5"
```

You can also pass them per run:

```powershell
papermatrix ./papers --out matrix.md --model gpt-5.5 --base-url https://api.dwai.cloud/v1 --api-mode responses
```

## Usage

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
  downloads/
    arxiv-2401.12345.pdf
    arxiv-2401.12345.source.json
    doi-a-paper-xxxxxxxxxxxx.pdf
    doi-a-paper-xxxxxxxxxxxx.source.json
  paper1_chunks.jsonl
  paper1_extract.json
  paper1_meta.json
```

`matrix.evidence.md` lists each non-unknown field value, evidence pages, chunk id, and the most relevant local source sentences so you can quickly check whether the LLM extracted the right information.

On repeated runs, PaperMatrix reuses existing `.papermatrix/*_extract.json` and `.papermatrix/*_meta.json` files when the metadata still matches, then skips PDF reading, chunking, and LLM calls for those papers. Metadata checks the PDF name, size, modification time, output language, model, API mode, base URL, `--max-chars`, `--max-chunks`, preset name, and complete extraction field configuration:

```bash
papermatrix ./papers --out matrix.md
```

To ignore cached extracts and rerun extraction:

```bash
papermatrix ./papers --out matrix.md --force
```

## Output Language

`--language` controls the final Markdown/CSV column names, unknown labels, and page markers:

- `zh`: default, uses Chinese headers such as `论文`, `研究问题`, and `方法`.
- `en`: uses English headers such as `Paper`, `Problem`, and `Method`.

In Chinese mode, the LLM is instructed to summarize extracted field values in Simplified Chinese when possible. Dataset names, metric names, model names, and other proper nouns may remain in their original form. Internal JSON still uses stable English keys for downstream processing.

## Current Limits

- No Web UI.
- No Zotero, chat QA, or table recognition.
- Extraction only uses selected chunks from each paper.
- Fields without explicit evidence are normalized to `unknown`; Chinese matrix output displays them as `未知`.
