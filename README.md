# PaperMatrix

语言：中文 | [English](README.en.md)

PaperMatrix 是一个轻量级 Python 命令行工具，用于把本地 PDF 论文文件夹转换成论文对比矩阵。它会读取 PDF、清洗并切块文本、选择和抽取最相关的片段、调用 LLM 生成结构化字段，最后导出 Markdown 和 CSV。

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

如果需要英文矩阵：

```bash
papermatrix ./papers --out matrix.md --language en
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
.papermatrix/
  paper1_chunks.jsonl
  paper1_extract.json
```

## 输出语言

`--language` 控制最终 Markdown/CSV 的列名、未知值和页码标注：

- `zh`：默认值，输出中文列名，例如 `论文`、`研究问题`、`方法`。
- `en`：输出英文列名，例如 `Paper`、`Problem`、`Method`。

中文模式下，LLM 会被要求尽量用简体中文概括字段值；数据集名、指标名、模型名等专有名词可以保留原文。内部 JSON 仍使用稳定的英文 key，方便后续程序处理。

## 当前限制

- 只支持本地 PDF 文件夹。
- 没有 Web UI。
- 不支持 arXiv、Zotero、对话问答或表格识别。
- 抽取只使用每篇论文中被选中的片段。
- 缺少明确证据的字段会被规范化为 `unknown`，最终中文矩阵中显示为 `未知`。
