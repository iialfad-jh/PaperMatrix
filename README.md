# PaperMatrix

语言：中文 | [English](README.en.md)

PaperMatrix 将本地 PDF、arXiv、DOI 和公开 PDF 链接整理成可核查的论文对比矩阵。它输出 Markdown、CSV 和带页码证据的摘录，方便快速比较与复核。

需要 Python 3.11 或更高版本。

## 安装

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[web]"
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[web]"
```

只使用命令行时可安装核心依赖：

```bash
python -m pip install -e .
```

## 配置 API Key

```bash
export OPENAI_API_KEY="your_api_key_here"
```

Windows PowerShell 使用：

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

兼容 OpenAI 的服务可另外设置 `OPENAI_BASE_URL`、`OPENAI_API_MODE` 和 `PAPERMATRIX_MODEL`，也可通过命令行参数传入。

## 使用

### Web 工作台

```bash
papermatrix web
```

打开 <http://127.0.0.1:8765> 后即可上传 PDF，或逐行输入 arXiv、DOI、PDF URL 和本地路径。页面支持选择字段预设、查看处理进度、重试失败项、查看证据 PDF，以及预览矩阵。

每个任务的 Markdown、CSV、证据和报告都会写入“结果文件夹”的项目子目录。默认是启动目录下的 `PaperMatrix Results`；在页面中改为其他本机文件夹后，历史结果会自动从其中的 Markdown 文件读取。

### 命令行

将一个目录中的 PDF 生成为矩阵：

```bash
papermatrix ./papers --out matrix.md
```

也可直接传入远程来源：

```bash
papermatrix arxiv:2401.12345 --out matrix.md
papermatrix doi:10.1234/example --out matrix.md
papermatrix https://example.org/paper.pdf --out matrix.md
```

常用选项：

```bash
# 英文输出
papermatrix ./papers --out matrix.md --language en

# 选择内置字段预设
papermatrix ./papers --out matrix.md --preset machine-learning

# 混合批量来源，每行一个 PDF、arXiv、DOI 或 URL
papermatrix --sources-file sources.txt --out matrix.md

# 忽略缓存，重新抽取
papermatrix ./papers --out matrix.md --force
```

使用 `papermatrix --list-presets` 查看可用预设。远程 PDF、抽取缓存和运行报告默认保存在 `.papermatrix/`。

## 输出

- `matrix.md`：论文对比矩阵
- `matrix.csv`：可导入表格工具的矩阵
- `matrix.evidence.md`：字段值及其页码、chunk 和原文证据

## 当前限制

- Web 工作台是本地单用户模式。
- 扫描件和纯图片表格暂不支持 OCR。
- 不支持 Zotero 导入或针对论文集的对话问答。
