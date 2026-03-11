/**
 * <sc-diff-viewer> — Inline diff viewer for YAML changes.
 *
 * Properties:
 *   .oldText = "original yaml"
 *   .newText = "modified yaml"
 *   .visible = true/false
 */
export class ScDiffViewer extends HTMLElement {
  constructor() {
    super();
    this._oldText = "";
    this._newText = "";
    this._visible = false;
    this._rendered = false;
  }

  set oldText(val) { this._oldText = val || ""; if (this._visible) this._update(); }
  set newText(val) { this._newText = val || ""; if (this._visible) this._update(); }

  set visible(val) {
    this._visible = !!val;
    if (this._rendered) {
      this.querySelector(".dv-wrap").classList.toggle("sc-hidden", !this._visible);
      if (this._visible) this._update();
    }
  }
  get visible() { return this._visible; }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .dv-wrap {
          flex-shrink: 0;
          max-height: 260px;
          overflow: auto;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--code-editor-background-color, #1e1e1e);
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 12px;
          line-height: 1.5;
        }
        .dv-header {
          position: sticky;
          top: 0;
          padding: 6px 12px;
          background: #252526;
          color: #ccc;
          font-size: 11px;
          font-weight: 600;
          border-bottom: 1px solid #333;
          z-index: 1;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .dv-stats { font-weight: 400; }
        .dv-stats .dv-add { color: #4ec9b0; }
        .dv-stats .dv-del { color: #f14c4c; }
        .dv-line { display: flex; white-space: pre; }
        .dv-num {
          min-width: 36px;
          text-align: right;
          padding: 0 6px;
          color: #585858;
          user-select: none;
          flex-shrink: 0;
        }
        .dv-code { flex: 1; padding: 0 8px; }
        .dv-add-line { background: rgba(78, 201, 176, 0.12); }
        .dv-add-line .dv-code { color: #4ec9b0; }
        .dv-add-line .dv-num { color: #4ec9b0; }
        .dv-del-line { background: rgba(241, 76, 76, 0.12); }
        .dv-del-line .dv-code { color: #f14c4c; }
        .dv-del-line .dv-num { color: #f14c4c; }
        .dv-ctx-line .dv-code { color: #888; }
        .dv-sep {
          padding: 2px 12px;
          color: #555;
          font-size: 11px;
          background: #1a1a2e;
        }
        .dv-no-changes {
          padding: 16px;
          text-align: center;
          color: #666;
        }
      </style>
      <div class="dv-wrap sc-hidden"></div>
    `;
  }

  _update() {
    const wrap = this.querySelector(".dv-wrap");
    if (!wrap) return;

    const oldLines = this._oldText.split("\n");
    const newLines = this._newText.split("\n");
    const diff = this._computeDiff(oldLines, newLines);

    if (!diff.length) {
      wrap.innerHTML = '<div class="dv-no-changes">No changes</div>';
      return;
    }

    let adds = 0, dels = 0;
    for (const d of diff) {
      if (d.type === "+") adds++;
      if (d.type === "-") dels++;
    }

    let html = `<div class="dv-header">
      <span>Diff</span>
      <span class="dv-stats"><span class="dv-add">+${adds}</span> <span class="dv-del">-${dels}</span></span>
    </div>`;

    for (const d of diff) {
      const cls = d.type === "+" ? "dv-add-line" : d.type === "-" ? "dv-del-line" : "dv-ctx-line";
      const prefix = d.type === "+" ? "+" : d.type === "-" ? "-" : " ";
      const num = d.lineNum || "";
      const code = this._escapeHtml(d.text);
      html += `<div class="dv-line ${cls}"><span class="dv-num">${num}</span><span class="dv-code">${prefix} ${code}</span></div>`;
    }

    wrap.innerHTML = html;
  }

  /**
   * Simple LCS-based diff algorithm.
   */
  _computeDiff(oldLines, newLines) {
    const m = oldLines.length;
    const n = newLines.length;

    // Build LCS table
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        if (oldLines[i - 1] === newLines[j - 1]) {
          dp[i][j] = dp[i - 1][j - 1] + 1;
        } else {
          dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
        }
      }
    }

    // Backtrack to get diff
    const raw = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
        raw.unshift({ type: " ", text: oldLines[i - 1], oldNum: i, newNum: j });
        i--; j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        raw.unshift({ type: "+", text: newLines[j - 1], newNum: j });
        j--;
      } else {
        raw.unshift({ type: "-", text: oldLines[i - 1], oldNum: i });
        i--;
      }
    }

    // Show only context around changes (3 lines)
    const result = [];
    const ctx = 3;
    const changeIndices = new Set();
    for (let k = 0; k < raw.length; k++) {
      if (raw[k].type !== " ") {
        for (let c = Math.max(0, k - ctx); c <= Math.min(raw.length - 1, k + ctx); c++) {
          changeIndices.add(c);
        }
      }
    }

    let lastShown = -1;
    for (let k = 0; k < raw.length; k++) {
      if (!changeIndices.has(k)) continue;
      if (lastShown >= 0 && k - lastShown > 1) {
        result.push({ type: "sep" });
      }
      const d = raw[k];
      d.lineNum = d.type === "-" ? d.oldNum : d.newNum || d.oldNum;
      result.push(d);
      lastShown = k;
    }

    return result;
  }

  _escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
}

customElements.define("sc-diff-viewer", ScDiffViewer);
