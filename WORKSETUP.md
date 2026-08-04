# PaperMatrix 工作交接

## 当前状态

- 分支：`main`；功能完成后推送至 `origin/main`，最新提交以 `git log -1` 为准。
- 已完成：本地 Web UI、模型/API 模式/推理档位、API Key 输入与可选本地保存、连接测试，以及运行选项自动恢复。
- 已完成：设置持久化异常场景覆盖，包括损坏的 `localStorage`、旧版本字段迁移、保存失败，以及 API Key 仅在勾选记住时保存。
- 已完成：多论文混合失败会按失败原因和论文文件汇总，任务级提示保留主要原因与脱敏技术详情。
- 错误提示已区分 API Key、网络、模型、API 模式、限流/余额、超时和 TLS/代理问题，并显示处理建议与技术详情。
- 最近验证：完整测试 `128 passed, 2 skipped`；浏览器验证结构化错误提示无溢出、无控制台错误，测试 Key 已清除。

## 快速开始

```powershell
pip install -e ".[test,web]"
python -m pytest
papermatrix web --no-open
```

浏览器访问 `http://127.0.0.1:8765/`。真实导出需要有效 API Key；可在 UI 输入，或设置 `OPENAI_API_KEY`。

## 关键位置

- Web 后端：`papermatrix/web.py`
- Web 前端：`papermatrix/web_assets/`
- LLM 配置：`papermatrix/llm.py`
- Web 测试：`tests/test_web.py`
- 使用说明：`README.md`、`README.en.md`

## 注意

- “记住 API Key”使用浏览器 `localStorage`，仅适合可信设备；Key 不写入报告、项目缓存或 Git。
- 默认模型为 `gpt-5.5`；推理强度 `auto` 表示不额外发送该参数。
- 外部论文下载和真实模型调用需要网络；常规测试默认不调用真实外部服务。
- 错误分类依据异常类型、HTTP 状态码和服务商消息；无法识别时保留脱敏技术详情与运行报告入口。

## 下一步计划

1. 用真实服务商配置做一次端到端多论文导出，确认 Markdown、CSV、证据文件和运行报告完整。

## 提交前检查

```powershell
python -m pytest
git diff --check
git status --short
```
