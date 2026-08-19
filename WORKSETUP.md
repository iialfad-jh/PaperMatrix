# PaperMatrix 交接指南

## 项目用途

PaperMatrix 将 PDF、arXiv、DOI 和公开 PDF URL 整理为带页码证据的 Markdown/CSV 论文比较矩阵。Web 工作台的主要代码在 `papermatrix/web.py` 和 `papermatrix/web_assets/`。

## 当前状态

- 默认模式是本机单用户工作台，启动时仅监听 `127.0.0.1`。
- PDF 证据查看器优先使用 PDF.js；Worker 或 Canvas 失败时会降级为浏览器原生 PDF 查看器。
- 结果目录受 `results_root` 限制。浏览器可选择该根目录内的子文件夹，不能读写任意服务器路径。
- 任务元数据写入 `.papermatrix/jobs/*.json`；重启后可重新查看已完成任务。服务重启时正在执行的任务会标记为失败，不会自动续跑。
- 服务器模式支持访问令牌、禁用服务器本地路径输入和反向代理子路径。

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,web]"
python -m pytest -q
papermatrix web --no-open
```

打开 `http://127.0.0.1:8765/`。真实抽取需要 `OPENAI_API_KEY`，可通过环境变量或页面输入。

## 服务器部署

不要把默认本地模式直接暴露到公网。服务器至少设置：

```bash
export PAPERMATRIX_WEB_AUTH_TOKEN="replace-with-a-long-random-token"
export PAPERMATRIX_RESULTS_ROOT="/srv/papermatrix/results"
export PAPERMATRIX_ALLOW_LOCAL_SOURCES=0
export PAPERMATRIX_WEB_SECURE_COOKIE=1
papermatrix web --host 127.0.0.1 --port 8765 --root-path /papermatrix --no-open
```

- `PAPERMATRIX_WEB_AUTH_TOKEN` 启用工作台会话认证。浏览器令牌只用于换取 HttpOnly Cookie，不写入浏览器存储或任务报告。
- `PAPERMATRIX_RESULTS_ROOT` 是唯一允许浏览、读取历史 Markdown 和写入结果的目录。
- `PAPERMATRIX_ALLOW_LOCAL_SOURCES=0` 禁止用户提交服务器本地路径；仍支持上传、arXiv、DOI 和 HTTP(S) PDF URL。
- `PAPERMATRIX_WEB_SECURE_COOKIE=1` 要求 HTTPS。反向代理必须终止 TLS。
- `--root-path /papermatrix` 用于应用位于 URL 子路径。反向代理应将 `/papermatrix/` 转发到本地服务根路径，并保留尾部斜杠。

认证由应用处理，但仍建议在反向代理层增加访问控制、上传大小限制和请求速率限制。

## 关键位置

- `papermatrix/web.py`：FastAPI 路由、认证、目录约束、任务恢复。
- `papermatrix/web_assets/app.js`：页面状态、会话登录、历史结果和证据查看。
- `papermatrix/web_assets/pdf-viewer.js`：PDF.js 与原生查看器降级前的页面渲染。
- `papermatrix/pipeline.py`：抽取、缓存、导出和运行报告。
- `tests/test_web.py`：Web API、路径安全、认证和重启恢复测试。

## 提交前检查

```bash
python -m pytest -q
node --check papermatrix/web_assets/app.js
node --check papermatrix/web_assets/pdf-viewer.js
git diff --check
git status --short
```

保留用户已有的未提交文件，尤其是结果目录和许可证文件的本地改动；不要通过 `git commit -a` 一并提交。
