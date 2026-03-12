/**
 * <sc-code-editor> — CodeMirror 6 editor wrapper for SmartChain panel.
 *
 * Loads pre-built CodeMirror bundle from local vendor/ directory via script tag,
 * provides YAML/JSON editor with unified diff view, custom actions,
 * and Jinja2+YAML syntax highlighting.
 *
 * Properties:
 *   .value / .language / .readonly / .diffMode / .originalValue
 *
 * Events:
 *   "change" { value }, "action" { id }, "ready", "diff-updated"
 */

const CM_BUNDLE_URL = "/smartchain/vendor/codemirror-bundle.min.js";

let cmLoaded = false;
let cmLoadPromise = null;

function loadCodeMirror() {
  if (cmLoaded) return Promise.resolve();
  if (cmLoadPromise) return cmLoadPromise;

  cmLoadPromise = new Promise((resolve, reject) => {
    if (window.CM?.EditorView) {
      cmLoaded = true;
      resolve();
      return;
    }

    const script = document.createElement("script");
    script.src = CM_BUNDLE_URL;
    script.onload = () => {
      if (window.CM?.EditorView) {
        cmLoaded = true;
        resolve();
      } else {
        reject(new Error("CodeMirror bundle loaded but CM global not found"));
      }
    };
    script.onerror = () => reject(new Error("Failed to load CodeMirror bundle"));
    document.head.appendChild(script);
  });

  return cmLoadPromise;
}

/* ---- Jinja2+YAML StreamParser ---- */
function jinja2YamlParser() {
  return {
    name: "jinja2-yaml",
    startState() {
      return { inJinjaBlock: false, inJinjaExpr: false, inJinjaComment: false };
    },
    token(stream, state) {
      if (state.inJinjaComment) {
        if (stream.match("#}")) { state.inJinjaComment = false; return "comment"; }
        stream.next();
        return "comment";
      }
      if (state.inJinjaBlock) {
        if (stream.match(/[-]?%\}/)) { state.inJinjaBlock = false; return "keyword"; }
        if (stream.match(/\b(if|else|elif|endif|for|endfor|block|endblock|macro|endmacro|set|include|import|from|extends|with|raw|endraw|call|endcall|filter|endfilter)\b/))
          return "keyword";
        if (stream.match(/"([^"\\]|\\.)*"/)) return "string";
        if (stream.match(/'([^'\\]|\\.)*'/)) return "string";
        if (stream.match(/\b\d+\.?\d*\b/)) return "number";
        if (stream.match(/[a-zA-Z_]\w*/)) return "variableName";
        stream.next();
        return "punctuation";
      }
      if (state.inJinjaExpr) {
        if (stream.match(/[-]?\}\}/)) { state.inJinjaExpr = false; return "brace"; }
        if (stream.match("|")) return "operator";
        if (stream.match(/"([^"\\]|\\.)*"/)) return "string";
        if (stream.match(/'([^'\\]|\\.)*'/)) return "string";
        if (stream.match(/\b\d+\.?\d*\b/)) return "number";
        if (stream.match(/[a-zA-Z_]\w*/)) return "variableName.special";
        stream.next();
        return "punctuation";
      }

      if (stream.match("{#")) { state.inJinjaComment = true; return "comment"; }
      if (stream.match(/\{%[-]?\s*/)) { state.inJinjaBlock = true; return "keyword"; }
      if (stream.match(/\{\{[-]?\s*/)) { state.inJinjaExpr = true; return "brace"; }

      if (stream.match(/#.*$/)) return "comment";
      if (stream.sol() && stream.match(/\s*[\w_.-]+(?=\s*:)/)) return "propertyName";
      if (stream.match(/"([^"\\]|\\.)*"/)) return "string";
      if (stream.match(/'([^'\\]|\\.)*'/)) return "string";
      if (stream.match(/\b(true|false|on|off|yes|no|null)\b/i)) return "bool";
      if (stream.match(/\b\d+\.?\d*\b/)) return "number";
      if (stream.match(/[a-z_]+\.[a-z0-9_.]+/)) return "typeName";

      stream.next();
      return null;
    },
  };
}

/* ---- Dark Theme ---- */
function smartchainDarkTheme() {
  return CM.EditorView.theme(
    {
      "&": {
        backgroundColor: "#1e1e1e",
        color: "#d4d4d4",
        fontSize: "13px",
        fontFamily: "'Roboto Mono', 'Fira Code', monospace",
      },
      /* height + overflow managed by _heightCompartment */
      ".cm-content": {
        caretColor: "#aeafad",
        lineHeight: "20px",
        padding: "8px 0",
      },
      "&.cm-focused .cm-cursor": { borderLeftColor: "#aeafad" },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
        { backgroundColor: "#264f78" },
      ".cm-panels": { backgroundColor: "#252526", color: "#cccccc" },
      ".cm-panels.cm-panels-top": { borderBottom: "1px solid #444" },
      ".cm-panels.cm-panels-bottom": { borderTop: "1px solid #444" },
      ".cm-searchMatch": { backgroundColor: "#515c6a", outline: "1px solid #74879f" },
      ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "#373d29" },
      ".cm-activeLine": { backgroundColor: "#2a2d2e" },
      ".cm-selectionMatch": { backgroundColor: "#373d29" },
      ".cm-matchingBracket, .cm-nonmatchingBracket": {
        backgroundColor: "#bad0f847",
        outline: "1px solid #515a6b",
      },
      ".cm-gutters": {
        backgroundColor: "#1e1e1e",
        color: "#858585",
        border: "none",
        minWidth: "40px",
      },
      ".cm-activeLineGutter": { backgroundColor: "#2a2d2e" },
      ".cm-foldPlaceholder": {
        backgroundColor: "transparent",
        border: "none",
        color: "#ddd",
      },
      ".cm-tooltip": {
        border: "1px solid #454545",
        backgroundColor: "#252526",
        color: "#cccccc",
      },
      ".cm-tooltip .cm-tooltip-arrow:before": { borderTopColor: "#454545", borderBottomColor: "#454545" },
      ".cm-tooltip .cm-tooltip-arrow:after": { borderTopColor: "#252526", borderBottomColor: "#252526" },
      ".cm-tooltip-autocomplete": { "& > ul > li[aria-selected]": { backgroundColor: "#094771", color: "#fff" } },
      ".cm-changedLine": { backgroundColor: "#2ea04326" },
      ".cm-changedText": { backgroundColor: "#2ea04366" },
      ".cm-deletedChunk": { backgroundColor: "#f8514926" },
    },
    { dark: true }
  );
}

/* ---- Syntax highlight colors ---- */
function smartchainHighlightStyle() {
  const style = CM.HighlightStyle.define([
    { tag: CM.tags.keyword, color: "#C586C0", fontWeight: "bold" },
    { tag: CM.tags.variableName, color: "#9CDCFE" },
    { tag: [CM.tags.special(CM.tags.variableName)], color: "#DCDCAA" },
    { tag: CM.tags.propertyName, color: "#9CDCFE" },
    { tag: CM.tags.typeName, color: "#4EC9B0" },
    { tag: CM.tags.string, color: "#CE9178" },
    { tag: CM.tags.number, color: "#B5CEA8" },
    { tag: CM.tags.bool, color: "#569CD6" },
    { tag: CM.tags.comment, color: "#6A9955", fontStyle: "italic" },
    { tag: CM.tags.operator, color: "#D4D4D4" },
    { tag: CM.tags.punctuation, color: "#D4D4D4" },
    { tag: CM.tags.brace, color: "#DCDCAA" },
  ]);
  return CM.syntaxHighlighting(style);
}

/* ---- Build extensions array ---- */
function buildExtensions(component, isDiff) {
  const lang =
    component._language === "json"
      ? CM.json()
      : component._language === "yaml"
        ? CM.yaml()
        : CM.StreamLanguage.define(jinja2YamlParser());

  const extensions = [
    CM.basicSetup,
    smartchainDarkTheme(),
    smartchainHighlightStyle(),
    lang,
    CM.EditorState.tabSize.of(2),
    CM.EditorView.lineWrapping,
    CM.EditorState.readOnly.of(component._readonly),
    CM.EditorView.editable.of(!component._readonly),
    CM.EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        component._value = update.state.doc.toString();
        component.dispatchEvent(
          new CustomEvent("change", { detail: { value: component._value } })
        );
      }
    }),
    CM.keymap.of([
      {
        key: "Mod-Shift-v",
        run: () => { component.dispatchEvent(new CustomEvent("action", { detail: { id: "validate" } })); return true; },
      },
      {
        key: "Mod-Shift-d",
        run: () => { component.dispatchEvent(new CustomEvent("action", { detail: { id: "deploy" } })); return true; },
      },
      {
        key: "Mod-Enter",
        run: () => { component.dispatchEvent(new CustomEvent("action", { detail: { id: "ai-apply" } })); return true; },
      },
      {
        key: "Mod-Shift-g",
        run: () => { component.dispatchEvent(new CustomEvent("action", { detail: { id: "diff" } })); return true; },
      },
      {
        key: "Mod-Shift-c",
        run: () => { navigator.clipboard.writeText(component.value); return true; },
      },
    ]),
  ];

  if (isDiff) {
    extensions.push(
      CM.unifiedMergeView({
        original: component._originalValue,
        highlightChanges: true,
        gutter: true,
        syntaxHighlightDeletions: true,
        mergeControls: false,
      })
    );
  }

  return extensions;
}

export class ScCodeEditor extends HTMLElement {
  constructor() {
    super();
    this._value = "";
    this._originalValue = "";
    this._language = "yaml";
    this._readonly = false;
    this._diffMode = false;
    this._renderSideBySide = true;
    this._view = null;
    this._rendered = false;
    this._ready = false;
    this._resizeObserver = null;
  }

  /* ---- Value ---- */
  set value(val) {
    this._value = val || "";
    if (!this._ready || !this._view) return;
    const current = this._view.state.doc.toString();
    if (current !== this._value) {
      this._view.dispatch({
        changes: { from: 0, to: current.length, insert: this._value },
      });
    }
  }

  get value() {
    if (!this._ready || !this._view) return this._value;
    return this._view.state.doc.toString();
  }

  /* ---- Language ---- */
  set language(val) {
    this._language = val || "yaml";
    if (this._ready) this._rebuildEditor();
  }

  /* ---- Readonly ---- */
  set readonly(val) {
    this._readonly = !!val;
    if (this._ready) this._rebuildEditor();
  }

  /* ---- Diff Mode ---- */
  set diffMode(val) {
    const newMode = !!val;
    if (newMode === this._diffMode) return;
    this._diffMode = newMode;
    if (this._ready) this._rebuildEditor();
  }

  get diffMode() {
    return this._diffMode;
  }

  forceNormalMode(newValue) {
    if (newValue !== undefined) this._value = newValue;

    if (this._diffMode) {
      this._diffMode = false;
      if (this._ready) this._rebuildEditor();
    } else if (this._ready && this._view) {
      const current = this._view.state.doc.toString();
      if (current !== this._value) {
        this._view.dispatch({
          changes: { from: 0, to: current.length, insert: this._value },
        });
      }
    }
  }

  /* ---- Original Value (for diff) ---- */
  set originalValue(val) {
    this._originalValue = val || "";
    if (this._ready && this._diffMode) {
      this._rebuildEditor();
    }
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

  disconnectedCallback() {
    this._disposeResizeObserver();
    this._destroyEditor();
  }

  _render() {
    this.innerHTML = `
      <style>
        .ce-wrap { flex: 1; min-height: 0; position: relative; overflow: hidden; }
        .ce-container {
          position: absolute; top: 0; left: 0; right: 0; bottom: 0;
          overflow: hidden;
        }
        .ce-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          height: 100%;
          color: var(--secondary-text-color, #888);
          font-size: 13px;
          background: var(--code-editor-background-color, #1e1e1e);
        }
      </style>
      <div class="ce-wrap">
        <div class="ce-loading">
          <span class="sc-spinner" style="border-color:rgba(255,255,255,0.15);border-top-color:var(--primary-color,#03a9f4);"></span>
          Loading editor...
        </div>
        <div class="ce-container" style="display:none;"></div>
      </div>
    `;
    this._initEditor();
  }

  async _initEditor() {
    try {
      await loadCodeMirror();
    } catch (err) {
      const loading = this.querySelector(".ce-loading");
      if (loading) loading.textContent = "Failed to load editor: " + err;
      return;
    }

    const loading = this.querySelector(".ce-loading");
    const container = this.querySelector(".ce-container");
    if (loading) loading.style.display = "none";
    if (container) container.style.display = "block";

    // Wait for browser to compute layout after display:none → block
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

    this._createEditor(container);
    this._setupResizeObserver(container);
    this._ready = true;

    const rect = container.getBoundingClientRect();
    const inlineH = this._view?.dom.style.height || "none";
    const computedH = this._view ? getComputedStyle(this._view.dom).height : "n/a";
    console.log("[sc-code-editor] ready, container:", rect.width, "x", rect.height,
      "editor-inline:", inlineH, "editor-computed:", computedH);

    this.dispatchEvent(new CustomEvent("ready"));
  }

  _createEditor(container) {
    const { height } = container.getBoundingClientRect();
    const pixelHeight = height > 0 ? height + "px" : "400px";

    const fixedTheme = CM.EditorView.theme({
      "&": { height: "100%", maxHeight: "100%" },
      ".cm-scroller": { overflow: "auto" },
    });

    const state = CM.EditorState.create({
      doc: this._value,
      extensions: [...buildExtensions(this, this._diffMode), fixedTheme],
    });

    this._view = new CM.EditorView({
      state,
      parent: container,
    });

    // Set explicit pixel height via inline style (most reliable for CM6)
    this._view.dom.style.height = pixelHeight;
    this._view.requestMeasure();

    if (this._diffMode) {
      setTimeout(() => {
        this.dispatchEvent(new CustomEvent("diff-updated"));
      }, 100);
    }
  }

  /** Update editor height from container dimensions */
  _syncEditorHeight(container) {
    if (!this._view) return;
    const { height } = container.getBoundingClientRect();
    if (height <= 0) return;
    this._view.dom.style.height = height + "px";
  }

  _setupResizeObserver(container) {
    this._disposeResizeObserver();
    this._resizeObserver = new ResizeObserver(() => {
      this._syncEditorHeight(container);
      if (this._view) this._view.requestMeasure();
    });
    this._resizeObserver.observe(container);
  }

  _disposeResizeObserver() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  _rebuildEditor() {
    const container = this.querySelector(".ce-container");
    if (!container || !cmLoaded) return;

    if (this._view) {
      this._value = this._view.state.doc.toString();
    }

    this._disposeResizeObserver();
    this._destroyEditor();
    container.innerHTML = "";
    this._createEditor(container);
    this._setupResizeObserver(container);
  }

  _destroyEditor() {
    if (this._view) {
      this._view.destroy();
      this._view = null;
    }
  }

  focus() {
    if (this._view) this._view.focus();
  }

  getDiffStats() {
    if (!this._diffMode || !this._view) return null;
    try {
      const result = CM.getChunks(this._view.state);
      if (!result || !result.chunks) return { additions: 0, deletions: 0, changes: 0 };
      const chunks = result.chunks;
      let additions = 0;
      let deletions = 0;
      for (const chunk of chunks) {
        const addedLines = chunk.endB - chunk.fromB;
        const deletedLines = chunk.endA - chunk.fromA;
        additions += addedLines > 0 ? addedLines : 0;
        deletions += deletedLines > 0 ? deletedLines : 0;
      }
      return { additions, deletions, changes: chunks.length };
    } catch {
      return { additions: 0, deletions: 0, changes: 0 };
    }
  }

  goToNextDiff() {
    if (this._diffMode && this._view) {
      try { CM.goToNextChunk(this._view); } catch { /* ignore */ }
    }
  }

  goToPrevDiff() {
    if (this._diffMode && this._view) {
      try { CM.goToPreviousChunk(this._view); } catch { /* ignore */ }
    }
  }

  set renderSideBySide(val) {
    this._renderSideBySide = !!val;
  }

  get renderSideBySide() {
    return this._renderSideBySide;
  }

  acceptChanges() {
    if (!this._diffMode || !this._view) return;
    this._value = this._view.state.doc.toString();
    this._originalValue = this._value;
    this._diffMode = false;
    this._rebuildEditor();
    this.dispatchEvent(
      new CustomEvent("change", { detail: { value: this._value } })
    );
  }

  revertChanges() {
    if (!this._diffMode || !this._view) return;
    this._value = this._originalValue;
    this._diffMode = false;
    this._rebuildEditor();
    this.dispatchEvent(
      new CustomEvent("change", { detail: { value: this._value } })
    );
  }
}

customElements.define("sc-code-editor", ScCodeEditor);
