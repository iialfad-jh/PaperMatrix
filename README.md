# PaperMatrix

语言：中文 | [English](README.en.md)

PaperMatrix 是一个轻量级 Python 命令行工具，用于把本地 PDF、arXiv 论文或直接 PDF 链接转换成论文对比矩阵。它会读取 PDF、清洗并切块文本、选择和抽取最相关的片段、调用 LLM 生成结构化字段，最后导出 Markdown、CSV 和证据文件。

## 安装

在项目目录创建虚拟环境：

```bash
python -m venv .venv
```

激活虚拟环境并安装项目：

```bash
.venv\Scripts\activate
pip install -e .
```

## API Key

运行前设置 `OPENAI_API_KEY`：

```bash
set OPENAI_API_KEY=your_api_key_here
```

PowerShell：

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

如果使用 OpenAI 兼容中转站，还需要设置接口地址和 API 模式：

```powershell
$env:OPENAI_API_KEY="your_relay_api_key_here"
$env:OPENAI_BASE_URL="https://api.dwai.cloud/v1"
$env:OPENAI_API_MODE="responses"
$env:PAPERMATRIX_MODEL="gpt-5.5"
```

也可以在单次运行时传入：

```powershell
papermatrix ./papers --out matrix.md --model gpt-5.5 --base-url https://api.dwai.cloud/v1 --api-mode responses
```

## 使用

默认输出中文矩阵：

```bash
papermatrix ./papers --out matrix.md
```

也可以直接传入 arXiv ID、arXiv 页面链接或 PDF 直链：

```bash
papermatrix arxiv:2401.12345 --out matrix.md
papermatrix https://arxiv.org/abs/2401.12345 --out matrix.md
papermatrix https://example.org/paper.pdf --out matrix.md
papermatrix doi:10.1234/example --out matrix.md
papermatrix https://doi.org/10.1234/example --out matrix.md
```

DOI 导入会先读取 Crossref 元数据，再尝试合法开放 PDF。设置 `UNPAYWALL_EMAIL` 后，还会查询 Unpaywall 的开放获取仓储：

```powershell
$env:UNPAYWALL_EMAIL="researcher@example.org"
papermatrix doi:10.1234/example --out matrix.md
```

如果 DOI 没有可访问的开放 PDF，程序会明确报错，不会把付费页面或登录页面保存成 PDF。远程 PDF 会缓存在 `.papermatrix/downloads/` 中；再次运行时会复用下载文件，使用 `--force` 会重新下载并重新抽取。

需要混合批量导入时，可以使用来源文件：

```powershell
papermatrix --sources-file sources.txt --out matrix.md
```

`sources.txt` 每行一个来源，支持空行和以 `#` 开头的注释；相对本地路径以来源文件所在目录为基准：

```text
# 本地 PDF、arXiv、DOI 和 PDF URL 可以混合使用
papers/local-paper.pdf
arxiv:2401.12345
doi:10.1234/example
https://example.org/paper.pdf
```

程序会规范化并去除重复的 arXiv、DOI、URL 和本地路径。单个来源失败时默认继续处理其余论文，并把逐项状态、错误信息和缓存文件写入 `.papermatrix/import-report.json`。需要在首个失败处停止时使用：

```powershell
papermatrix --sources-file sources.txt --out matrix.md --fail-fast
```

如果需要英文矩阵：

```bash
papermatrix ./papers --out matrix.md --language en
```

如果需要自定义矩阵列，可以用逗号传入字段名：

```bash
papermatrix ./papers --out matrix.md --fields problem,method,input,output,dataset,result
```

也可以直接使用内置字段预设：

```powershell
papermatrix ./papers --out matrix.md --preset general
papermatrix ./papers --out matrix.md --preset machine-learning
papermatrix ./papers --out matrix.md --preset plant-growth
papermatrix ./papers --out matrix.md --preset survey
```

查看所有预设或某个预设的完整 JSON 配置时，不需要传入论文来源：

```powershell
papermatrix --list-presets
papermatrix --show-preset plant-growth
```

`general` 适合一般实验论文，`machine-learning` 增加模型输入输出和基线，`plant-growth` 增加作物、发育阶段、处理与环境，`survey` 面向综述的检索范围、分类体系和研究空白。`--preset` 与 `--fields` 不能同时使用；需要调整预设时，可参考 `--show-preset` 的输出创建自己的 fields JSON。

字段名会作为内部 JSON key 使用，请使用英文字母、数字和下划线，例如 `model_input`、`crop_species`、`future_output`。默认字段仍然是 `problem,method,dataset,metric,result,limitation`。

如果需要更明确的列名、字段说明和选块关键词，也可以传入 JSON 配置文件：

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

输入：

```text
papers/
  paper1.pdf
  paper2.pdf
```

输出：

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

`matrix.evidence.md` 会列出每个非未知字段的抽取值、证据页码、chunk id 和最相关的本地原文句子，方便快速复核 LLM 是否摘对。

再次运行时，如果 `.papermatrix/*_extract.json` 和 `.papermatrix/*_meta.json` 已存在且元数据匹配，PaperMatrix 会默认复用缓存的抽取结果，跳过对应 PDF 的读取、切块和 LLM 调用。元数据会检查 PDF 文件名、大小、修改时间、输出语言、模型、API 模式、base URL、`--max-chars`、`--max-chunks`、预设名称和完整抽取字段配置：

```bash
papermatrix ./papers --out matrix.md
```

如果需要忽略缓存并重新抽取：

```bash
papermatrix ./papers --out matrix.md --force
```

## 输出语言

`--language` 控制最终 Markdown/CSV 的列名、未知值和页码标注：

- `zh`：默认值，输出中文列名，例如 `论文`、`研究问题`、`方法`。
- `en`：输出英文列名，例如 `Paper`、`Problem`、`Method`。

中文模式下，LLM 会被要求尽量用简体中文概括字段值；数据集名、指标名、模型名等专有名词可以保留原文。内部 JSON 仍使用稳定的英文 key，方便后续程序处理。

## 当前限制

- 没有 Web UI。
- 不支持 Zotero、对话问答或表格识别。
- 抽取只使用每篇论文中被选中的片段。
- 缺少明确证据的字段会被规范化为 `unknown`，最终中文矩阵中显示为 `未知`。
