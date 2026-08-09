import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


APP_JS = Path(__file__).resolve().parents[1] / "papermatrix" / "web_assets" / "app.js"


def run_settings_script(tmp_path: Path, scenario: str) -> None:
    if not shutil.which("node"):
        pytest.skip("node is required for browser settings tests")

    runner = tmp_path / "settings-test.mjs"
    runner.write_text(
        textwrap.dedent(
            """
            import fs from "node:fs";
            import vm from "node:vm";
            import assert from "node:assert/strict";

            class ClassList {
              constructor(element) {
                this.element = element;
                this.values = new Set(String(element.className || "").split(/\\s+/).filter(Boolean));
              }

              sync() { this.element.className = Array.from(this.values).join(" "); }
              add(...names) { names.forEach((name) => this.values.add(name)); this.sync(); }
              remove(...names) { names.forEach((name) => this.values.delete(name)); this.sync(); }
              toggle(name, force) {
                const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
                if (enabled) this.values.add(name); else this.values.delete(name);
                this.sync();
                return enabled;
              }
            }

            class Element {
              constructor(selector) {
                this.selector = selector;
                this.value = "";
                this.checked = false;
                this.disabled = false;
                this.required = false;
                this.textContent = "";
                this.innerHTML = "";
                this.className = "";
                this.placeholder = "";
                this.files = [];
                this.dataset = {};
                this.style = {};
                this.children = [];
                this.listeners = {};
                this.classList = new ClassList(this);
              }

              addEventListener(name, handler) { this.listeners[name] = handler; }
              append(...children) { this.children.push(...children); }
              replaceChildren(...children) {
                this.children = children;
                this.textContent = "";
                this.innerHTML = "";
              }
              querySelector(selector) { return element(`${this.selector} ${selector}`); }
              closest() { return null; }
            }

            const elements = new Map();
            const namedControls = new Map();
            function element(selector) {
              if (!elements.has(selector)) elements.set(selector, new Element(selector));
              return elements.get(selector);
            }
            function control(selector, name, value = "") {
              const node = element(selector);
              node.name = name;
              node.value = value;
              namedControls.set(name, node);
              return node;
            }

            const form = element("#job-form");
            form.elements = { namedItem: (name) => namedControls.get(name) || null };
            const controls = {
              language: control("#language", "language", "zh"),
              preset: control("#preset", "preset", "general"),
              fields: control("#fields", "fields", ""),
              model: control("#model", "model", ""),
              baseUrl: control("#base-url", "base_url", ""),
              apiMode: control("#api-mode", "api_mode", "chat"),
              reasoning: control("#reasoning-effort", "reasoning_effort", "auto"),
              maxChars: control("#max-chars", "max_chars", "3500"),
              maxChunks: control("#max-chunks", "max_chunks", "12"),
              retries: control("#retries", "retries", "2"),
              force: control("[name='force']", "force"),
              failFast: control("[name='fail_fast']", "fail_fast"),
              apiKey: control("#api-key", "api_key", ""),
              remember: control("#remember-api-key", "remember_api_key")
            };
            [
              "#settings-status", "#files", "#file-note", "#custom-fields-wrap", "#reasoning-hint",
              "#test-provider", "#cancel-job", "#retry-job", "#recent-jobs", "#form-error",
              "#provider-probe-status", "#matrix-preview", "#result-summary", "#field-visibility",
              "#field-toggles", "#show-all-fields", "[data-testid='health']"
            ].forEach((selector) => element(selector));

            const storage = {
              data: new Map(),
              throwGet: false,
              throwSet: false,
              getItem(key) {
                if (this.throwGet) throw new Error("storage unavailable");
                return this.data.has(key) ? this.data.get(key) : null;
              },
              setItem(key, value) {
                if (this.throwSet) throw new Error("quota exceeded");
                this.data.set(key, String(value));
              }
            };
            const document = {
              querySelector: (selector) => element(selector),
              createElement: (tag) => new Element(tag)
            };
            const window = {};
            const context = {
              console, assert, setTimeout, clearTimeout, document, window,
              localStorage: storage,
              EventSource: class {},
              FormData: class { set() {} },
              fetch: async (url) => ({
                ok: true,
                status: 200,
                json: async () => {
                  if (url === "/api/config") {
                    return {
                      defaults: {
                        language: "zh",
                        preset: "general",
                        model: "gpt-5.5",
                        api_mode: "chat",
                        reasoning_effort: "auto"
                      },
                      presets: [{ name: "general", description_zh: "通用" }]
                    };
                  }
                  if (url === "/api/jobs") return { jobs: [] };
                  return {};
                }
              })
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context, { filename: "app.js" });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const PaperMatrixWeb = context.window.PaperMatrixWeb;
            const key = PaperMatrixWeb.settingsStorageKey;
            __SCENARIO__
            """
        ).replace("__SCENARIO__", textwrap.indent(scenario, "            "))
        ,
        encoding="utf-8",
    )

    result = subprocess.run(["node", str(runner), str(APP_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout


def test_web_settings_restore_uses_defaults_when_saved_json_is_corrupt(tmp_path: Path):
    run_settings_script(
        tmp_path,
        """
        storage.data.set(key, "{not-json");
        controls.apiMode.value = "chat";
        controls.reasoning.value = "auto";

        assert.equal(Object.keys(PaperMatrixWeb.readSavedSettings()).length, 0);
        PaperMatrixWeb.restoreSettings();

        assert.equal(controls.apiMode.value, "chat");
        assert.equal(controls.reasoning.value, "auto");
        assert.match(element("#settings-status").textContent, /无法读取浏览器保存的设置/);
        """,
    )


def test_web_settings_restore_accepts_legacy_and_missing_fields(tmp_path: Path):
    run_settings_script(
        tmp_path,
        """
        storage.data.set(key, JSON.stringify({
          language: "en",
          apiMode: "responses",
          reasoningEffort: "medium",
          maxChars: "4200",
          failFast: true,
          rememberApiKey: true,
          apiKey: "sk-legacy-secret"
        }));
        controls.preset.value = "general";
        controls.maxChunks.value = "12";

        PaperMatrixWeb.restoreSettings();

        assert.equal(controls.language.value, "en");
        assert.equal(controls.apiMode.value, "responses");
        assert.equal(controls.reasoning.value, "medium");
        assert.equal(controls.maxChars.value, "4200");
        assert.equal(controls.failFast.checked, true);
        assert.equal(controls.remember.checked, true);
        assert.equal(controls.apiKey.value, "sk-legacy-secret");
        assert.equal(controls.preset.value, "general");
        assert.equal(controls.maxChunks.value, "12");
        """,
    )


def test_web_settings_save_handles_storage_failures_and_key_opt_in(tmp_path: Path):
    run_settings_script(
        tmp_path,
        """
        controls.language.value = "en";
        controls.apiMode.value = "responses";
        controls.remember.checked = true;
        controls.apiKey.value = "sk-save-secret";
        storage.throwSet = true;

        assert.doesNotThrow(() => PaperMatrixWeb.saveSettings());
        assert.match(element("#settings-status").textContent, /浏览器拒绝保存设置/);

        storage.throwSet = false;
        controls.remember.checked = false;
        PaperMatrixWeb.saveSettings();
        const saved = JSON.parse(storage.data.get(key));

        assert.equal(saved.language, "en");
        assert.equal(saved.api_mode, "responses");
        assert.equal(saved.remember_api_key, false);
        assert.equal(Object.hasOwn(saved, "api_key"), false);
        assert.equal(element("#settings-status").className, "hint settings-status hidden");
        """,
    )


def test_matrix_preview_renders_field_comparison_safely(tmp_path: Path):
    run_settings_script(
        tmp_path,
        """
        PaperMatrixWeb.setMatrixPreview({
          columns: ["Paper", "Method", "Result"],
          rows: [{ Paper: "Study <One>", Method: "Trial", Result: "A & B" }]
        });

        const markup = element("#matrix-preview").innerHTML;
        assert.match(markup, /<th scope="row">Study &lt;One&gt;<\\/th>/);
        assert.match(markup, /data-field="Method">Trial<\\/td>/);
        assert.match(markup, /A &amp; B/);
        assert.equal(element("#result-summary").textContent, "1 篇论文 · 2/2 个字段显示");

        PaperMatrixWeb.setFieldVisibility(1, false);
        const hiddenMarkup = element("#matrix-preview").innerHTML;
        assert.doesNotMatch(hiddenMarkup, /Method/);
        assert.match(hiddenMarkup, /Result/);
        assert.match(hiddenMarkup, /<th scope="row">Study &lt;One&gt;<\\/th>/);
        assert.equal(element("#result-summary").textContent, "1 篇论文 · 1/2 个字段显示");

        PaperMatrixWeb.showAllFields();
        assert.match(element("#matrix-preview").innerHTML, /Method/);
        assert.equal(element("#show-all-fields").disabled, true);
        """,
    )
