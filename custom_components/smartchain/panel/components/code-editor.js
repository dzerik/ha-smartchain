/**
 * <sc-code-editor> — Full-featured YAML code editor with syntax highlighting,
 * line numbers, always-edit mode.
 *
 * Properties:
 *   .value = "yaml string" — get/set content
 *   .readonly = true/false
 *
 * Events:
 *   "change" — fired on every content change
 */
export class ScCodeEditor extends HTMLElement {
  constructor() {
    super();
    this._value = "";
    this._rendered = false;
    this._readonly = false;
  }

  set value(val) {
    this._value = val || "";
    if (this._rendered) {
      const ta = this.querySelector(".ce-textarea");
      if (ta && ta.value !== this._value) {
        ta.value = this._value;
      }
      this._syncLines();
    }
  }
  get value() {
    if (this._rendered) {
      const ta = this.querySelector(".ce-textarea");
      if (ta) return ta.value;
    }
    return this._value;
  }

  set readonly(val) {
    this._readonly = !!val;
    const ta = this.querySelector(".ce-textarea");
    if (ta) ta.readOnly = this._readonly;
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
        .ce-wrap {
          display: flex;
          flex: 1;
          overflow: hidden;
          background: var(--code-editor-background-color, #1e1e1e);
          position: relative;
          min-height: 0;
        }
        .ce-lines {
          padding: 10px 8px 10px 12px;
          text-align: right;
          user-select: none;
          font-family: var(--code-font-family, 'Roboto Mono', 'Fira Code', monospace);
          font-size: 13px;
          line-height: 1.6;
          color: #585858;
          min-width: 36px;
          flex-shrink: 0;
          white-space: pre;
          border-right: 1px solid #333;
          overflow: hidden;
        }
        .ce-textarea {
          flex: 1;
          padding: 10px 12px 10px 10px;
          font-family: var(--code-font-family, 'Roboto Mono', 'Fira Code', monospace);
          font-size: 13px;
          line-height: 1.6;
          color: #d4d4d4;
          background: transparent;
          border: none;
          outline: none;
          resize: none;
          white-space: pre;
          overflow: auto;
          tab-size: 2;
          width: 100%;
          box-sizing: border-box;
          caret-color: #fff;
        }
        .ce-textarea::placeholder { color: #555; }
        .ce-empty-msg {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          color: #555;
          font-size: 14px;
          text-align: center;
          pointer-events: none;
        }
      </style>
      <div class="ce-wrap">
        <div class="ce-lines">1</div>
        <textarea class="ce-textarea" spellcheck="false"
          placeholder="Select an item from the sidebar or create new..."></textarea>
        <div class="ce-empty-msg sc-hidden"></div>
      </div>
    `;

    const ta = this.querySelector(".ce-textarea");
    ta.value = this._value;
    ta.readOnly = this._readonly;
    this._syncLines();

    ta.addEventListener("input", () => {
      this._value = ta.value;
      this._syncLines();
      this.dispatchEvent(new CustomEvent("change", { detail: { value: this._value } }));
    });

    // Sync scroll for line numbers
    ta.addEventListener("scroll", () => {
      const lines = this.querySelector(".ce-lines");
      if (lines) lines.scrollTop = ta.scrollTop;
    });

    // Tab key inserts spaces
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        ta.value = ta.value.substring(0, start) + "  " + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 2;
        this._value = ta.value;
        this._syncLines();
        this.dispatchEvent(new CustomEvent("change", { detail: { value: this._value } }));
      }
    });
  }

  _syncLines() {
    const linesEl = this.querySelector(".ce-lines");
    if (!linesEl) return;
    const count = (this._value || "").split("\n").length;
    const nums = [];
    for (let i = 1; i <= count; i++) nums.push(i);
    linesEl.textContent = nums.join("\n");
  }

  focus() {
    const ta = this.querySelector(".ce-textarea");
    if (ta) ta.focus();
  }
}

customElements.define("sc-code-editor", ScCodeEditor);
