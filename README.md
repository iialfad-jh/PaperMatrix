# PaperMatrix

语言：中文 | [English](README.en.md)

PaperMatrix 是一个轻量级 Python 命令行工具，用于把本地 PDF、arXiv 论文或直接 PDF 链接转换成论文对比矩阵。它会读取 PDF、清洗并切块文本、选择和抽取最相关的片段、调用 LLM 生成结构化字段，最后导出 Markdown、CSV 和证据文件。支持 Windows、macOS 和 Linux，需要 Python 3.11 或更高版本。

## 安装

虚拟环境与操作系统绑定，不能在 Windows 和 macOS/Linux 之间复制复用。请在当前系统上重新创建 `.venv`。

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[web]"
```

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[web]"
```

只使用命令行时，可以省略 Web 可选依赖：

```bash
python -m pip install -e .
```

## API Key

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

macOS/Linux：

```bash
export OPENAI_API_KEY="your_api_key_here"
```

如果使用 OpenAI 兼容中转站，还需要设置接口地址和 API 模式：

```powershell
$env:OPENAI_API_KEY="your_relay_api_key_here"
$env:OPENAI_BASE_URL="https://api.dwai.cloud/v1"
$env:OPENAI_API_MODE="responses"
$env:PAPERMATRIX_MODEL="gpt-5.5"
$env:PAPERMATRIX_REASONING_EFFORT="medium"
```

macOS/Linux 使用相同变量名，并将 PowerShell 的 `$env:NAME="value"` 写法改为 `export NAME="value"`。

也可以在单次运行时传入：

```powershell
papermatrix ./papers --out matrix.md --model gpt-5.5 --base-url https://api.dwai.cloud/v1 --api-mode responses --reasoning-effort medium
```

推理强度支持 `auto`、`low`、`medium` 和 `high`。`auto` 不向服务商发送额外参数，使用模型默认值；论文结构化抽取通常建议从 `low` 或 `medium` 开始。

## 使用

### 本地 Web UI

启动浏览器工作台：

```bash
papermatrix web
```

服务默认只监听 `http://127.0.0.1:8765`。页面支持上传多个 PDF，或逐行输入本地路径、arXiv、DOI 和 PDF URL；可以选择输出语言与字段预设，实时查看结构化进度，取消任务、重试失败项，并预览或下载 Markdown、CSV、证据文件和运行报告。高级设置中的“测试连接”可以在上传论文前验证当前模型配置。连接或运行失败时，页面会区分 API Key、网络、模型、API 模式、限流/余额、超时和 TLS/代理问题，并直接显示处理建议与技术详情。页面会在当前浏览器中保存最近使用的运行选项；API Key 可以按任务输入、留空读取 `OPENAI_API_KEY`，或主动勾选“记住 API Key”保存到浏览器本地存储。密钥不会写入任务报告、项目缓存或 Git。

如果不希望自动打开系统浏览器，或需要修改端口：

```bash
papermatrix web --no-open --port 9000
```

### 命令行

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

论文处理阶段也会逐篇隔离：某篇 PDF 损坏或 LLM 请求失败时，程序会记录错误并继续处理其余论文。下载、元数据和 LLM API 的瞬时错误默认重试 2 次，永久性请求错误不会重试；可用 `--retries` 调整上限：

```powershell
papermatrix --sources-file sources.txt --out matrix.md --retries 4
```

每次处理都会写入 `.papermatrix/run-report.json`，其中保留每篇论文的状态、已完成阶段、重试上限和错误摘要。下面的命令只重新处理状态为 `pdf_failed`、`llm_failed`、`skipped` 或 `cancelled` 的论文，同时复用成功结果和原运行配置：

```powershell
papermatrix --retry-failed .papermatrix/run-report.json
```

`--retry-failed` 适用于已经解析出本地 PDF 路径的论文。来源导入失败仍记录在 `import-report.json` 中；重新执行原来的 `--sources-file` 命令即可重试这些来源，已下载文件仍会命中缓存。

对于需要反复运行的长期任务，可以用稳定项目 ID 隔离缓存、下载文件、抽取结果和运行报告：

```powershell
papermatrix ./papers --out matrix.md --project-id literature-review-2026
```

项目工作区会写入 `.papermatrix/projects/literature-review-2026/`。不传 `--project-id` 时仍使用原来的 `.papermatrix/`，保持向后兼容。重试命令会从运行报告恢复工作区，因此 `--retry-failed` 与 `--project-id` 不同时使用。

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

## 管线 API

CLI 已改为调用 `papermatrix.pipeline` 中与终端无关的处理引擎。Python 前端可以创建 `PipelineConfig`，调用 `run_pipeline(...)`，并从 `PipelineResult` 获取输出路径和完整运行报告。

通过 `progress_callback` 可以接收结构化 `ProgressEvent`，覆盖运行、PDF、LLM、论文、缓存和导出阶段。传入 `CancellationToken` 后，任务会在阶段之间安全停止；已经完成的抽取结果仍可复用，尚未完成的论文会记录为 `cancelled`，之后可用 `--retry-failed` 续跑。即使 UI 进度监听器断开并抛出异常，也不会中止后台处理任务。

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

`matrix.evidence.md` 会列出每个非未知字段的抽取值、证据页码、chunk id，以及最相关的本地原文句子或表格行，方便快速复核 LLM 是否摘对。

PaperMatrix 会优先检测带边框的 PDF 表格，对无边框布局再尝试文本表格检测。表格会保存成结构化 `table` chunk，保留表头、数据行、坐标和页码；相邻页首尾表格的表头一致时会自动合并，大表只在完整数据行之间拆分。数据集、指标、结果以及名称相近的自定义字段会优先选择相关表格。表格检测失败时，普通页面文本抽取仍会继续。

再次运行时，如果 `.papermatrix/*_extract.json` 和 `.papermatrix/*_meta.json` 已存在且元数据匹配，PaperMatrix 会默认复用缓存的抽取结果，跳过对应 PDF 的读取、切块和 LLM 调用。元数据会检查 PDF 文件名、大小、修改时间、输出语言、模型、API 模式、base URL、`--max-chars`、`--max-chunks`、预设名称和完整抽取字段配置：

```bash
papermatrix ./papers --out matrix.md
```

表格感知版本提升了缓存格式版本，因此旧版本生成的抽取缓存会自动重建一次，之后继续正常复用。

如果需要忽略缓存并重新抽取：

```bash
papermatrix ./papers --out matrix.md --force
```

默认测试套件完全离线。真实服务测试需要显式开启：

Windows PowerShell：

```powershell
$env:PAPERMATRIX_RUN_INTEGRATION="1"
python -m pytest -m integration
```

macOS/Linux：

```bash
PAPERMATRIX_RUN_INTEGRATION=1 python -m pytest -m integration
```

设置该变量后会执行 arXiv 下载检查；如需执行极小的真实 LLM 检查，还要设置 `PAPERMATRIX_RUN_LLM_INTEGRATION=1` 和 `OPENAI_API_KEY`。

## 输出语言

`--language` 控制最终 Markdown/CSV 的列名、未知值和页码标注：

- `zh`：默认值，输出中文列名，例如 `论文`、`研究问题`、`方法`。
- `en`：输出英文列名，例如 `Paper`、`Problem`、`Method`。

中文模式下，LLM 会被要求尽量用简体中文概括字段值；数据集名、指标名、模型名等专有名词可以保留原文。内部 JSON 仍使用稳定的英文 key，方便后续程序处理。

## 当前限制

- Web UI 目前是本地单用户模式，服务重启后不会恢复页面中的会话列表；项目文件和运行报告仍保留在 `.papermatrix/projects/`。
- 不支持 Zotero 或对话问答。
- 扫描件或纯图片表格仍需要 OCR，目前无法识别。
- 抽取只使用每篇论文中被选中的片段。
- 缺少明确证据的字段会被规范化为 `unknown`，最终中文矩阵中显示为 `未知`。
