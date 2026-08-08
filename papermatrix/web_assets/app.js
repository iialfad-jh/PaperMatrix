const state = { currentJobId: null, currentJob: null, previewJobId: null, eventSource: null, events: [], jobs: [] };

const $ = (selector) => document.querySelector(selector);
const statusLabels = {
  queued: "排队中", running: "处理中", cancelling: "正在取消", completed: "已完成", failed: "失败", cancelled: "已取消"
};
const phaseLabels = { import: "导入来源", pdf: "解析 PDF", llm: "抽取字段", paper: "处理论文", cache: "检查缓存", export: "导出结果", run: "运行任务" };
const artifactLabels = { markdown: "Markdown", csv: "CSV", evidence: "证据", report: "运行报告", import_report: "导入报告" };
const settingsStorageKey = "papermatrix.web.settings.v1";
const persistedValueNames = [
  "language", "preset", "fields", "model", "base_url", "api_mode", "reasoning_effort", "max_chars", "max_chunks", "retries"
];
const persistedCheckboxNames = ["force", "fail_fast"];
const legacySettingsNames = {
  apiMode: "api_mode",
  reasoningEffort: "reasoning_effort",
  maxChars: "max_chars",
  maxChunks: "max_chunks",
  failFast: "fail_fast",
  rememberApiKey: "remember_api_key",
  apiKey: "api_key"
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* no JSON body */ }
  if (!response.ok) {
    const detail = payload.error && typeof payload.error === "object" ? payload.error : null;
    const requestError = new Error(detail?.message || payload.detail || `请求失败（${response.status}）`);
    requestError.detail = detail;
    throw requestError;
  }
  return payload;
}

function showError(target, error) {
  target.replaceChildren();
  if (!error) {
    target.classList.add("hidden");
    return;
  }
  target.classList.remove("hidden");
  if (typeof error === "string") {
    target.textContent = error;
    return;
  }

  const title = document.createElement("strong");
  title.className = "error-title";
  title.textContent = error.title || "请求失败";
  target.append(title);
  if (error.message) {
    const message = document.createElement("p");
    message.textContent = error.message;
    target.append(message);
  }
  if (error.action) {
    const action = document.createElement("p");
    action.className = "error-action";
    action.textContent = `建议：${error.action}`;
    target.append(action);
  }
  if (error.failure_summary) {
    target.append(renderFailureSummary(error.failure_summary));
  }
  if (error.technical) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const technical = document.createElement("code");
    summary.textContent = "技术详情";
    technical.textContent = error.technical;
    details.append(summary, technical);
    target.append(details);
  }
}

function renderFailureSummary(summary) {
  const wrap = document.createElement("div");
  wrap.className = "failure-summary";
  const stats = document.createElement("p");
  stats.textContent = `论文汇总：${summary.exported || 0}/${summary.total || 0} 篇已导出，${summary.failed || 0} 篇失败。`;
  wrap.append(stats);
  (summary.groups || []).forEach((group) => {
    const section = document.createElement("section");
    const heading = document.createElement("strong");
    const list = document.createElement("ul");
    heading.textContent = `${group.title || "失败"}（${group.count || 0} 篇）`;
    section.append(heading);
    (group.papers || []).slice(0, 6).forEach((paper) => {
      const item = document.createElement("li");
      const name = paper.filename || paper.paper_id || "paper";
      item.textContent = paper.status ? `${name} · ${paper.status}` : name;
      if (paper.technical) item.title = paper.technical;
      list.append(item);
    });
    if ((group.papers || []).length > 6) {
      const item = document.createElement("li");
      item.textContent = `还有 ${(group.papers || []).length - 6} 篇，请查看运行报告。`;
      list.append(item);
    }
    section.append(list);
    wrap.append(section);
  });
  return wrap;
}

function setSettingsStatus(message, tone = "") {
  const target = $("#settings-status");
  if (!target) return;
  target.textContent = message || "";
  target.className = message ? `hint settings-status ${tone}`.trim() : "hint settings-status hidden";
}

function normalizeSavedSettings(settings) {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) return {};
  const normalized = { ...settings };
  Object.entries(legacySettingsNames).forEach(([legacyName, currentName]) => {
    if (normalized[currentName] === undefined && typeof normalized[legacyName] !== "undefined") {
      normalized[currentName] = normalized[legacyName];
    }
  });
  return normalized;
}

function readSavedSettings() {
  try {
    const raw = localStorage.getItem(settingsStorageKey);
    if (!raw) return {};
    return normalizeSavedSettings(JSON.parse(raw));
  } catch (_) {
    setSettingsStatus("无法读取浏览器保存的设置，已使用默认值。", "warning");
    return {};
  }
}

function saveSettings() {
  const form = $("#job-form");
  const settings = {};
  persistedValueNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input) settings[name] = input.value;
  });
  persistedCheckboxNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input) settings[name] = input.checked;
  });
  settings.remember_api_key = $("#remember-api-key").checked;
  if (settings.remember_api_key) settings.api_key = $("#api-key").value;
  try {
    localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    setSettingsStatus("");
  } catch (_) {
    setSettingsStatus("浏览器拒绝保存设置，本次仍可继续使用。", "warning");
  }
}

function restoreSettings() {
  const settings = readSavedSettings();
  const form = $("#job-form");
  persistedValueNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input && typeof settings[name] === "string") input.value = settings[name];
  });
  persistedCheckboxNames.forEach((name) => {
    const input = form.elements.namedItem(name);
    if (input && typeof settings[name] === "boolean") input.checked = settings[name];
  });
  $("#remember-api-key").checked = settings.remember_api_key === true;
  if (settings.remember_api_key === true && typeof settings.api_key === "string") {
    $("#api-key").value = settings.api_key;
  }
}

async function loadConfig() {
  const config = await api("/api/config");
  const select = $("#preset");
  select.innerHTML = config.presets.map((preset) => `<option value="${escapeHtml(preset.name)}">${escapeHtml(preset.description_zh || preset.name)}</option>`).join("") + '<option value="">自定义字段…</option>';
  select.value = config.defaults.preset;
  $("#language").value = config.defaults.language;
  $("#model").placeholder = config.defaults.model;
  $("#api-mode").value = config.defaults.api_mode;
  $("#reasoning-effort").value = config.defaults.reasoning_effort;
  restoreSettings();
  updateReasoningAvailability();
}

function updateFileNote() {
  const files = $("#files").files;
  $("#file-note").textContent = files.length ? `已选择 ${files.length} 个 PDF：${Array.from(files).slice(0, 2).map((f) => f.name).join("、")}${files.length > 2 ? "…" : ""}` : "支持多选，单个文件不超过 200 MB";
}

function toggleCustomFields() {
  const custom = $("#preset").value === "";
  $("#custom-fields-wrap").classList.toggle("hidden", !custom);
  $("#fields").required = custom;
}

function updateReasoningAvailability() {
  const model = ($("#model").value.trim() || $("#model").placeholder.trim()).toLowerCase();
  const select = $("#reasoning-effort");
  const knownNonReasoningModel = /^(gpt-3\.5|gpt-4)(?:[.-]|$)/.test(model);
  select.disabled = knownNonReasoningModel;
  if (knownNonReasoningModel) select.value = "auto";
  $("#reasoning-hint").textContent = knownNonReasoningModel
    ? "当前模型不支持推理强度，将使用自动模式。"
    : "档位越高通常越慢；论文结构化抽取建议使用低或中。";
}

function eventDescription(progress) {
  const phase = phaseLabels[progress.phase] || progress.phase;
  const names = { started: "开始", completed: "完成", failed: "失败", stale: "缓存已过期", cache_hit: "命中缓存", cancelled: "已取消" };
  const subject = progress.filename ? ` · ${progress.filename}` : "";
  return `${phase}${subject}：${names[progress.status] || progress.status}`;
}

function progressValue(job) {
  if (["completed"].includes(job.status)) return 100;
  if (["failed", "cancelled"].includes(job.status) && job.artifacts.csv) return 100;
  const progress = job.latest_progress;
  if (!progress) return job.status === "queued" ? 3 : 7;
  if (progress.phase === "import") return progress.status === "completed" ? 15 : 8;
  if (progress.phase === "export") return 96;
  if (progress.phase === "run" && progress.status === "completed") return 100;
  const index = Number(progress.index || 0);
  const total = Number(progress.total || 0);
  if (total && index) {
    const within = progress.phase === "llm" ? .75 : progress.phase === "paper" ? .95 : .35;
    return Math.min(94, Math.round(15 + ((index - 1 + within) / total) * 78));
  }
  return 18;
}

function renderEvents() {
  const list = $("#event-list");
  if (!state.events.length) {
    list.innerHTML = '<div class="event"><span class="event-dot"></span><span>任务已进入队列</span><small>等待</small></div>';
    return;
  }
  list.innerHTML = state.events.slice(-10).reverse().map((event) => {
    const data = event.data || {};
    const description = event.type === "progress" ? eventDescription(data) : `任务状态：${statusLabels[data.status] || data.status}`;
    const time = data.created_at ? new Date(data.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
    return `<div class="event"><span class="event-dot"></span><span>${escapeHtml(description)}</span><small>${escapeHtml(time)}</small></div>`;
  }).join("");
}

function updateJob(job) {
  if (state.currentJobId !== job.id) {
    state.previewJobId = null;
    $("#results").classList.add("hidden");
  }
  state.currentJobId = job.id;
  state.currentJob = job;
  $("#empty-state").classList.add("hidden");
  $("#job-view").classList.remove("hidden");
  $("#active-project").textContent = job.project_id;
  $("#active-job").textContent = job.id.slice(0, 8);
  const status = $("#job-status");
  status.textContent = statusLabels[job.status] || job.status;
  status.className = `status ${job.status}`;
  const value = progressValue(job);
  $("#progress-bar").style.width = `${value}%`;
  const label = job.latest_progress ? eventDescription(job.latest_progress) : (statusLabels[job.status] || "准备中");
  $("#progress-label").innerHTML = `<span>${escapeHtml(label)}</span><b>${value}%</b>`;
  showError($("#job-error"), job.error_detail || job.error || "");
  $("#cancel-job").classList.toggle("hidden", !job.can_cancel);
  $("#retry-job").classList.toggle("hidden", !job.can_retry);
  renderEvents();
  renderDownloads(job.artifacts || {});
  if (job.artifacts && job.artifacts.csv) {
    if (state.previewJobId !== job.id) {
      state.previewJobId = job.id;
      loadPreview(job.id);
    }
  } else {
    $("#results").classList.add("hidden");
  }
}

function renderDownloads(artifacts) {
  $("#downloads").innerHTML = Object.entries(artifacts).map(([name, href]) => `<a href="${escapeHtml(href)}" download>${escapeHtml(artifactLabels[name] || name)} ↓</a>`).join("");
}

async function loadPreview(jobId) {
  try {
    const preview = await api(`/api/jobs/${jobId}/preview`);
    if (jobId !== state.currentJobId) return;
    renderMatrixPreview(preview);
    $("#evidence-preview").textContent = preview.evidence || "暂无证据文件。";
    $("#results").classList.remove("hidden");
  } catch (error) {
    showError($("#job-error"), error.message);
  }
}

function renderMatrixPreview(preview) {
  const columns = Array.isArray(preview?.columns) ? preview.columns : [];
  const rows = Array.isArray(preview?.rows) ? preview.rows : [];
  const fieldCount = Math.max(0, columns.length - 1);
  $("#result-summary").textContent = `${rows.length} 篇论文 · ${fieldCount} 个比较字段`;
  if (!columns.length) {
    $("#matrix-preview").innerHTML = '<p class="muted matrix-empty">暂无可预览字段。</p>';
    return;
  }
  const head = columns.map((column, index) => (
    `<th scope="col"><span class="column-number">${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(column)}</strong></th>`
  )).join("");
  const body = rows.map((row) => `<tr>${columns.map((column, index) => {
    const value = escapeHtml(row?.[column]);
    return index === 0
      ? `<th scope="row">${value}</th>`
      : `<td data-field="${escapeHtml(column)}">${value}</td>`;
  }).join("")}</tr>`).join("");
  $("#matrix-preview").innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function connectEvents(jobId) {
  if (state.eventSource) state.eventSource.close();
  state.events = [];
  renderEvents();
  state.eventSource = new EventSource(`/api/jobs/${jobId}/events`);
  state.eventSource.onmessage = (message) => {
    const event = JSON.parse(message.data);
    state.events.push(event);
    if (event.type === "progress") {
      api(`/api/jobs/${jobId}`).then(updateJob).catch((error) => showError($("#job-error"), error.message));
    } else if (event.type === "job") {
      updateJob(event.data);
      loadJobs();
      if (["completed", "failed", "cancelled"].includes(event.data.status)) state.eventSource.close();
    }
  };
  state.eventSource.onerror = () => {
    if (state.eventSource) state.eventSource.close();
    api(`/api/jobs/${jobId}`).then(updateJob).catch((error) => showError($("#job-error"), error.message));
  };
}

async function submitJob(event) {
  event.preventDefault();
  const button = $("[data-testid='submit-job']");
  showError($("#form-error"), "");
  button.disabled = true;
  button.querySelector("span").textContent = "正在提交…";
  try {
    const formData = new FormData(event.currentTarget);
    const job = await api("/api/jobs", { method: "POST", body: formData });
    saveSettings();
    if (!$("#remember-api-key").checked) $("#api-key").value = "";
    updateJob(job);
    loadJobs();
    connectEvents(job.id);
  } catch (error) {
    showError($("#form-error"), error.message);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "开始生成矩阵";
  }
}

async function testProvider() {
  const button = $("#test-provider");
  const status = $("#provider-probe-status");
  const formData = new FormData();
  ["language", "model", "api_key", "base_url", "api_mode", "reasoning_effort"].forEach((name) => {
    formData.set(name, $("#job-form").elements.namedItem(name).value);
  });
  status.className = "notice hidden";
  button.disabled = true;
  button.textContent = "正在测试…";
  try {
    const payload = await api("/api/provider-probe", { method: "POST", body: formData });
    saveSettings();
    status.textContent = payload.message;
    status.className = "notice success";
  } catch (error) {
    status.className = "notice error";
    showError(status, error.detail || { title: "连接失败", message: error.message });
  } finally {
    button.disabled = false;
    button.textContent = "测试连接";
  }
}

async function loadJobs() {
  try {
    const payload = await api("/api/jobs");
    state.jobs = payload.jobs;
    const container = $("#recent-jobs");
    if (!state.jobs.length) {
      container.innerHTML = '<p class="muted">还没有任务。</p>';
      return;
    }
    container.innerHTML = state.jobs.slice(0, 6).map((job) => `<button type="button" class="recent-job" data-job-id="${escapeHtml(job.id)}"><strong>${escapeHtml(job.project_id)}</strong><span class="mini-status">${escapeHtml(statusLabels[job.status] || job.status)}</span><small>${new Date(job.created_at).toLocaleString()}</small></button>`).join("");
  } catch (_) { /* health state already communicates server errors */ }
}

async function selectJob(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    state.events = [];
    updateJob(job);
    if (job.can_cancel) connectEvents(job.id);
  } catch (error) { showError($("#job-error"), error.message); }
}

async function cancelCurrent() {
  if (!state.currentJobId) return;
  try { updateJob(await api(`/api/jobs/${state.currentJobId}/cancel`, { method: "POST" })); loadJobs(); }
  catch (error) { showError($("#job-error"), error.message); }
}

async function retryCurrent() {
  if (!state.currentJobId) return;
  try {
    const job = await api(`/api/jobs/${state.currentJobId}/retry`, { method: "POST" });
    updateJob(job);
    loadJobs();
    connectEvents(job.id);
  } catch (error) { showError($("#job-error"), error.message); }
}

async function bootstrap() {
  try {
    await Promise.all([loadConfig(), loadJobs(), api("/api/health")]);
  } catch (error) {
    const health = $("[data-testid='health']");
    health.textContent = "服务不可用";
    health.classList.add("offline");
    showError($("#form-error"), error.message);
  }
  toggleCustomFields();
}

function bindUi() {
  $("#job-form").addEventListener("submit", submitJob);
  $("#job-form").addEventListener("change", saveSettings);
  $("#files").addEventListener("change", updateFileNote);
  $("#preset").addEventListener("change", toggleCustomFields);
  $("#model").addEventListener("input", updateReasoningAvailability);
  $("#test-provider").addEventListener("click", testProvider);
  $("#cancel-job").addEventListener("click", cancelCurrent);
  $("#retry-job").addEventListener("click", retryCurrent);
  $("#recent-jobs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-job-id]");
    if (button) selectJob(button.dataset.jobId);
  });
}

if (typeof window !== "undefined") {
  window.PaperMatrixWeb = { readSavedSettings, saveSettings, restoreSettings, renderMatrixPreview, settingsStorageKey };
}

if (typeof document !== "undefined") {
  bindUi();
  bootstrap();
}
