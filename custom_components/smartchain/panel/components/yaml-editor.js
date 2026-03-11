/**
 * <sc-yaml-editor> — YAML editor with syntax highlighting, line numbers, and edit/preview toggle.
 *
 * Properties:
 *   .value = "yaml string"  — get/set YAML content
 *   .readonly = true/false
 *   .label = "YAML" — header label
 *
 * Events:
 *   "change" — fired when content changes in edit mode
 */
export class ScYamlEditor extends HTMLElement {
  constructor() {
    super();
    this._value = "";
    this._editing = false;
    this._label = "YAML";
    this._rendered = false;
  }

  set value(val) {
    this._value = val || "";
    if (this._rendered) this._updateDisplay();
  }
  get value() {
    if (this._editing) {
      const ta = this.querySelector(".ye-textarea");
      if (ta) this._value = ta.value;
    }
    return this._value;
  }

  set label(val) {
    this._label = val || "YAML";
    const info = this.querySelector(".ye-info");
    if (info) this._updateInfo();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .ye-wrap {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          overflow: hidden;
        }
        .ye-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .ye-header-actions { display: flex; gap: 8px; align-items: center; }
        .ye-toggle {
          background: none; border: none;
          color: var(--primary-color, #03a9f4);
          cursor: pointer; font-size: 12px;
          padding: 2px 6px; border-radius: 4px;
        }
        .ye-toggle:hover { background: var(--divider-color, #e0e0e0); }
        .ye-body {
          display: flex;
          max-height: 500px;
          overflow: auto;
          background: var(--code-editor-background-color, #1e1e1e);
        }
        .ye-lines {
          padding: 12px 8px 12px 12px;
          text-align: right;
          user-select: none;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #858585;
          min-width: 32px;
          flex-shrink: 0;
          white-space: pre;
          border-right: 1px solid #333;
        }
        .ye-display {
          flex: 1;
          padding: 12px 12px 12px 8px;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #d4d4d4;
          white-space: pre;
          overflow-x: auto;
        }
        .ye-textarea {
          flex: 1;
          padding: 12px 12px 12px 8px;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #d4d4d4;
          background: transparent;
          border: none;
          outline: none;
          resize: none;
          min-height: 200px;
          white-space: pre;
          overflow-x: auto;
          tab-size: 2;
          width: 100%;
          box-sizing: border-box;
        }
        /* Syntax highlighting */
        .hl-key { color: #9cdcfe; }
        .hl-str { color: #ce9178; }
        .hl-num { color: #b5cea8; }
        .hl-bool { color: #569cd6; }
        .hl-cmt { color: #6a9955; font-style: italic; }
        .hl-ent { color: #4ec9b0; }
        .ye-hidden { display: none !important; }
      </style>
      <div class="ye-wrap">
        <div class="ye-header">
          <span class="ye-info"></span>
          <div class="ye-header-actions">
            <button class="ye-toggle">Edit</button>
          </div>
        </div>
        <div class="ye-body">
          <div class="ye-lines"></div>
          <div class="ye-display"></div>
          <textarea class="ye-textarea ye-hidden"></textarea>
        </div>
      </div>
    `;

    this.querySelector(".ye-toggle").addEventListener("click", () => this._toggleEdit());
    this._updateDisplay();
  }

  _updateDisplay() {
    const lines = this._value.split("\n");
    const linesEl = this.querySelector(".ye-lines");
    const displayEl = this.querySelector(".ye-display");
    const textareaEl = this.querySelector(".ye-textarea");

    if (linesEl) linesEl.innerHTML = lines.map((_, i) => i + 1).join("\n");
    if (displayEl) displayEl.innerHTML = this._highlight(this._value);
    if (textareaEl) textareaEl.value = this._value;
    this._updateInfo();
  }

  _updateInfo() {
    const info = this.querySelector(".ye-info");
    if (info) {
      const lineCount = this._value.split("\n").length;
      info.textContent = `${this._label} \u2014 ${lineCount} lines`;
    }
  }

  _toggleEdit() {
    const displayEl = this.querySelector(".ye-display");
    const textareaEl = this.querySelector(".ye-textarea");
    const toggleBtn = this.querySelector(".ye-toggle");

    if (this._editing) {
      // Save and switch to preview
      this._value = textareaEl.value;
      this._updateDisplay();
      textareaEl.classList.add("ye-hidden");
      displayEl.classList.remove("ye-hidden");
      toggleBtn.textContent = "Edit";
      this._editing = false;
      this.dispatchEvent(new CustomEvent("change", { detail: { value: this._value } }));
    } else {
      // Switch to edit mode
      textareaEl.value = this._value;
      displayEl.classList.add("ye-hidden");
      textareaEl.classList.remove("ye-hidden");
      toggleBtn.textContent = "Preview";
      this._editing = true;
      textareaEl.focus();
    }
  }

  _highlight(yaml) {
    const escaped = yaml
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    return escaped.split("\n").map((line) => {
      if (line.trimStart().startsWith("#")) {
        return `<span class="hl-cmt">${line}</span>`;
      }
      return line.replace(
        /^(\s*)([\w_.-]+)(:)(.*)/,
        (_match, indent, key, colon, rest) => {
          let hl = rest;
          hl = hl.replace(/\b([a-z_]+\.[a-z0-9_]+)\b/g, '<span class="hl-ent">$1</span>');
          hl = hl.replace(/(["'])(.*?)\1/g, '<span class="hl-str">$1$2$1</span>');
          hl = hl.replace(/\b(true|false|on|off)\b/gi, '<span class="hl-bool">$1</span>');
          hl = hl.replace(/\b(\d+\.?\d*)\b/g, '<span class="hl-num">$1</span>');
          return `${indent}<span class="hl-key">${key}</span>${colon}${hl}`;
        }
      );
    }).join("\n");
  }
}

customElements.define("sc-yaml-editor", ScYamlEditor);
