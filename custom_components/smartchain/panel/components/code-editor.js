/**
 * <sc-code-editor> — wraps HA's built-in <ha-code-editor> (CodeMirror 6).
 *
 * Normal mode: uses ha-code-editor with YAML syntax highlighting, autocomplete, toolbar.
 * Diff mode: simple line-level diff view (added/removed/unchanged lines).
 *
 * Properties:
 *   .value / .language / .readonly / .diffMode / .originalValue / .hass
 *
 * Events:
 *   "change" { value }, "action" { id }, "ready", "diff-updated"
 */

/* ---- Simple line diff ---- */
function computeLineDiff(original, modified) {
  const oldLines = (original || "").split("\n");
  const newLines = (modified || "").split("\n");
  const result = [];

  // Simple LCS-based diff
  const n = oldLines.length;
  const m = newLines.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      dp[i][j] = oldLines[i - 1] === newLines[j - 1]
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }

  let i = n, j = m;
  const ops = [];
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      ops.push({ type: "same", text: newLines[j - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ type: "add", text: newLines[j - 1] });
      j--;
    } else {
      ops.push({ type: "del", text: oldLines[i - 1] });
      i--;
    }
  }
  ops.reverse();
  return ops;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export class ScCodeEditor extends HTMLElement {
  constructor() {
    super();
    this._value = "";
    this._originalValue = "";
    this._language = "yaml";
    this._readonly = false;
    this._diffMode = false;
    this._hass = null;
    this._rendered = false;
    this._ready = false;
    this._diffOps = null;
  }

  /* ---- Hass ---- */
  set hass(val) {
    this._hass = val;
    const ed = this.querySelector("ha-code-editor");
    if (ed) {
      ed.hass = val;
      if (val) ed.autocompleteEntities = true;
    }
  }

  /* ---- Value ---- */
  set value(val) {
    this._value = val || "";
    if (this._diffMode) {
      this._renderDiff();
      return;
    }
    const ed = this.querySelector("ha-code-editor");
    if (ed) ed.value = this._value;
  }

  get value() {
    if (this._diffMode) return this._value;
    const ed = this.querySelector("ha-code-editor");
    return ed ? (ed.value ?? this._value) : this._value;
  }

  /* ---- Language ---- */
  set language(val) {
    this._language = val || "yaml";
    const ed = this.querySelector("ha-code-editor");
    if (ed) ed.mode = this._language;
  }

  /* ---- Readonly ---- */
  set readonly(val) {
    this._readonly = !!val;
    const ed = this.querySelector("ha-code-editor");
    if (ed) ed.readOnly = this._readonly;
  }

  /* ---- Diff Mode ---- */
  set diffMode(val) {
    const newMode = !!val;
    if (newMode === this._diffMode) return;
    this._diffMode = newMode;
    this._toggleView();
  }

  get diffMode() {
    return this._diffMode;
  }

  forceNormalMode(newValue) {
    if (newValue !== undefined) this._value = newValue;
    this._diffMode = false;
    this._toggleView();
    const ed = this.querySelector("ha-code-editor");
    if (ed) ed.value = this._value;
  }

  /* ---- Original Value (for diff) ---- */
  set originalValue(val) {
    this._originalValue = val || "";
    if (this._diffMode) this._renderDiff();
  }

  /* ---- Lifecycle ---- */
  connectedCallback() {
    if (!this._rendered) {
      this.style.cssText =
        "display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden;";
      this._render();
      this._rendered = true;
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .ce-wrap {
          flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden;
        }
        .ce-editor-wrap {
          flex: 1; min-height: 0; display: flex; flex-direction: column;
          --code-mirror-height: 100%;
          --code-mirror-max-height: 100%;
        }
        .ce-editor-wrap ha-code-editor {
          flex: 1; min-height: 0; display: block;
        }
        .ce-diff {
          flex: 1; min-height: 0; overflow: auto;
          font-family: 'Roboto Mono', 'Fira Code', monospace;
          font-size: 13px;
          line-height: 20px;
          background: var(--code-editor-background-color, var(--card-background-color, #1e1e1e));
          color: var(--primary-text-color, #d4d4d4);
        }
        .ce-diff-table {
          width: 100%;
          border-collapse: collapse;
        }
        .ce-diff-table td {
          padding: 0 8px;
          white-space: pre;
          vertical-align: top;
        }
        .ce-diff-table .ce-ln {
          width: 1px;
          text-align: right;
          color: var(--secondary-text-color, #858585);
          user-select: none;
          padding: 0 6px;
          opacity: 0.6;
        }
        .ce-diff-table .ce-add { background: rgba(46, 160, 67, 0.15); }
        .ce-diff-table .ce-del { background: rgba(248, 81, 73, 0.15); }
        .ce-diff-table .ce-add .ce-sign { color: #3fb950; }
        .ce-diff-table .ce-del .ce-sign { color: #f85149; }
        .ce-diff-table .ce-sign {
          width: 1px;
          padding: 0 4px;
          user-select: none;
        }
        .ce-validation {
          max-height: 140px;
          overflow-y: auto;
          font-size: 13px;
          line-height: 1.6;
          padding: 8px 12px;
          border-top: 1px solid var(--divider-color, #444);
          background: var(--card-background-color, #1e1e1e);
        }
        .ce-val-item {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          padding: 2px 0;
          cursor: pointer;
          border-radius: 4px;
        }
        .ce-val-item:hover { background: rgba(255,255,255,0.05); }
        .ce-val-item.ce-err { color: var(--error-color, #f44336); }
        .ce-val-item.ce-warn { color: var(--warning-color, #ff9800); }
        .ce-val-icon { flex-shrink: 0; width: 16px; text-align: center; }
        .ce-val-line {
          flex-shrink: 0; min-width: 40px;
          color: var(--secondary-text-color, #888); font-size: 11px;
          font-family: 'Roboto Mono', monospace;
        }
        .ce-val-msg { flex: 1; }
      </style>
      <div class="ce-wrap">
        <div class="ce-editor-wrap">
          <ha-code-editor mode="${this._language}" linewrap></ha-code-editor>
        </div>
        <div class="ce-diff" style="display:none;"></div>
        <div class="ce-validation" style="display:none;"></div>
      </div>
    `;

    const ed = this.querySelector("ha-code-editor");
    if (ed) {
      ed.hasToolbar = false;
      ed.value = this._value;
      if (this._hass) {
        ed.hass = this._hass;
        ed.autocompleteEntities = true;
      }

      ed.addEventListener("value-changed", (e) => {
        if (this._diffMode) return;
        this._value = e.detail.value ?? "";
        this.dispatchEvent(
          new CustomEvent("change", { detail: { value: this._value } })
        );
      });

      ed.addEventListener("editor-save", () => {
        this.dispatchEvent(new CustomEvent("action", { detail: { id: "deploy" } }));
      });
    }

    // Keyboard shortcuts on the wrapper
    this.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
        switch (e.key.toLowerCase()) {
          case "v":
            e.preventDefault();
            this.dispatchEvent(new CustomEvent("action", { detail: { id: "validate" } }));
            break;
          case "d":
            e.preventDefault();
            this.dispatchEvent(new CustomEvent("action", { detail: { id: "deploy" } }));
            break;
          case "g":
            e.preventDefault();
            this.dispatchEvent(new CustomEvent("action", { detail: { id: "diff" } }));
            break;
        }
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        this.dispatchEvent(new CustomEvent("action", { detail: { id: "ai-apply" } }));
      }
    });

    this._ready = true;
    this.dispatchEvent(new CustomEvent("ready"));
  }

  _toggleView() {
    const editorWrap = this.querySelector(".ce-editor-wrap");
    const diffWrap = this.querySelector(".ce-diff");
    if (!editorWrap || !diffWrap) return;

    if (this._diffMode) {
      editorWrap.style.display = "none";
      diffWrap.style.display = "";
      this._renderDiff();
    } else {
      editorWrap.style.display = "";
      diffWrap.style.display = "none";
      const ed = this.querySelector("ha-code-editor");
      if (ed) ed.value = this._value;
    }
  }

  _renderDiff() {
    const diffWrap = this.querySelector(".ce-diff");
    if (!diffWrap) return;

    this._diffOps = computeLineDiff(this._originalValue, this._value);

    let oldLn = 0, newLn = 0;
    const rows = this._diffOps.map((op) => {
      let cls = "";
      let sign = " ";
      let leftNum = "", rightNum = "";

      if (op.type === "same") {
        oldLn++; newLn++;
        leftNum = oldLn; rightNum = newLn;
      } else if (op.type === "add") {
        newLn++;
        cls = "ce-add";
        sign = "+";
        rightNum = newLn;
      } else {
        oldLn++;
        cls = "ce-del";
        sign = "−";
        leftNum = oldLn;
      }

      return `<tr class="${cls}"><td class="ce-ln">${leftNum}</td><td class="ce-ln">${rightNum}</td><td class="ce-sign">${sign}</td><td>${escapeHtml(op.text)}</td></tr>`;
    }).join("");

    diffWrap.innerHTML = `<table class="ce-diff-table">${rows}</table>`;

    setTimeout(() => {
      this.dispatchEvent(new CustomEvent("diff-updated"));
    }, 50);
  }

  /* ---- Diff operations ---- */
  getDiffStats() {
    if (!this._diffOps) return { additions: 0, deletions: 0, changes: 0 };
    let additions = 0, deletions = 0;
    for (const op of this._diffOps) {
      if (op.type === "add") additions++;
      else if (op.type === "del") deletions++;
    }
    return { additions, deletions, changes: additions + deletions };
  }

  goToNextDiff() {
    const diffWrap = this.querySelector(".ce-diff");
    if (!diffWrap) return;
    const rows = diffWrap.querySelectorAll("tr.ce-add, tr.ce-del");
    if (rows.length === 0) return;
    // Find first diff row below current scroll position
    const scrollTop = diffWrap.scrollTop;
    for (const row of rows) {
      if (row.offsetTop > scrollTop + 10) {
        diffWrap.scrollTo({ top: row.offsetTop - 40, behavior: "smooth" });
        return;
      }
    }
    // Wrap around
    diffWrap.scrollTo({ top: rows[0].offsetTop - 40, behavior: "smooth" });
  }

  goToPrevDiff() {
    const diffWrap = this.querySelector(".ce-diff");
    if (!diffWrap) return;
    const rows = diffWrap.querySelectorAll("tr.ce-add, tr.ce-del");
    if (rows.length === 0) return;
    const scrollTop = diffWrap.scrollTop;
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].offsetTop < scrollTop - 10) {
        diffWrap.scrollTo({ top: rows[i].offsetTop - 40, behavior: "smooth" });
        return;
      }
    }
    diffWrap.scrollTo({ top: rows[rows.length - 1].offsetTop - 40, behavior: "smooth" });
  }

  set renderSideBySide(_val) { /* no-op, single view only */ }
  get renderSideBySide() { return false; }

  acceptChanges() {
    if (!this._diffMode) return;
    this._originalValue = this._value;
    this._diffMode = false;
    this._diffOps = null;
    this._toggleView();
    this.dispatchEvent(
      new CustomEvent("change", { detail: { value: this._value } })
    );
  }

  revertChanges() {
    if (!this._diffMode) return;
    this._value = this._originalValue;
    this._diffMode = false;
    this._diffOps = null;
    this._toggleView();
    this.dispatchEvent(
      new CustomEvent("change", { detail: { value: this._value } })
    );
  }

  focus() {
    const ed = this.querySelector("ha-code-editor");
    if (ed?.codemirror) ed.codemirror.focus();
  }

  /* ---- Validation ---- */
  setValidation(data) {
    const panel = this.querySelector(".ce-validation");
    if (!panel) return;

    const items = [];
    const yaml = this._value || "";
    const lines = yaml.split("\n");

    for (const err of (data.errors || [])) {
      const line = this._findLineForError(err, lines);
      items.push({ type: "err", msg: err, line });
    }
    for (const warn of (data.warnings || [])) {
      const line = this._findLineForError(warn, lines);
      items.push({ type: "warn", msg: warn, line });
    }

    if (items.length === 0) {
      panel.style.display = "none";
      return;
    }

    panel.style.display = "";
    panel.innerHTML = items.map((item) => {
      const icon = item.type === "err" ? "✕" : "⚠";
      const cls = item.type === "err" ? "ce-err" : "ce-warn";
      const lineLabel = item.line > 0 ? `L${item.line}` : "";
      return `<div class="ce-val-item ${cls}" data-line="${item.line}"><span class="ce-val-icon">${icon}</span><span class="ce-val-line">${lineLabel}</span><span class="ce-val-msg">${escapeHtml(item.msg)}</span></div>`;
    }).join("");

    // Click to scroll to line
    panel.querySelectorAll(".ce-val-item").forEach((el) => {
      el.addEventListener("click", () => {
        const lineNum = parseInt(el.dataset.line, 10);
        if (lineNum > 0) this._scrollToLine(lineNum);
      });
    });
  }

  clearValidation() {
    const panel = this.querySelector(".ce-validation");
    if (panel) {
      panel.style.display = "none";
      panel.innerHTML = "";
    }
  }

  _findLineForError(errorMsg, lines) {
    // Try to extract key name from error message
    const keyMatch = errorMsg.match(/Missing required key: '([^']+)'/);
    if (keyMatch) {
      // For missing keys, we can't find the line — return 0
      return 0;
    }

    const entityMatch = errorMsg.match(/Entity '([^']+)'/);
    if (entityMatch) {
      const entity = entityMatch[1];
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes(entity)) return i + 1;
      }
    }

    const serviceMatch = errorMsg.match(/Service '([^']+)'/);
    if (serviceMatch) {
      const svc = serviceMatch[1];
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes(svc)) return i + 1;
      }
    }

    // Try to find any quoted string from error in the YAML
    const quotedMatch = errorMsg.match(/'([^']+)'/);
    if (quotedMatch) {
      const term = quotedMatch[1];
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes(term)) return i + 1;
      }
    }

    return 0;
  }

  _scrollToLine(lineNum) {
    const ed = this.querySelector("ha-code-editor");
    if (!ed?.codemirror) return;
    const cm = ed.codemirror;
    const line = cm.state.doc.line(Math.min(lineNum, cm.state.doc.lines));
    cm.dispatch({
      selection: { anchor: line.from },
      scrollIntoView: true,
    });
    cm.focus();
  }
}

customElements.define("sc-code-editor", ScCodeEditor);
