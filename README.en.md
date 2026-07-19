# PaperMatrix

Language: [中文](README.md) | English

PaperMatrix is a lightweight Python CLI for turning a local folder of PDF papers into a comparison matrix. It reads PDFs, cleans and chunks paper text, selects extraction-relevant chunks, asks an LLM for structured fields, and exports Markdown, CSV, and evidence files.

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

For English matrix output:

```bash
papermatrix ./papers --out matrix.md --language en
```

To customize matrix columns, pass comma-separated field names:

```bash
papermatrix ./papers --out matrix.md --fields problem,method,input,output,dataset,result
```

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
  paper1_chunks.jsonl
  paper1_extract.json
  paper1_meta.json
```

`matrix.evidence.md` lists each non-unknown field value, evidence pages, chunk id, and the most relevant local source sentences so you can quickly check whether the LLM extracted the right information.

On repeated runs, PaperMatrix reuses existing `.papermatrix/*_extract.json` and `.papermatrix/*_meta.json` files when the metadata still matches, then skips PDF reading, chunking, and LLM calls for those papers. Metadata checks the PDF name, size, modification time, output language, model, API mode, base URL, `--max-chars`, `--max-chunks`, and extraction fields:

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

- Local PDF folders only.
- No Web UI.
- No arXiv, Zotero, chat QA, or table recognition.
- Extraction only uses selected chunks from each paper.
- Fields without explicit evidence are normalized to `unknown`; Chinese matrix output displays them as `未知`.
