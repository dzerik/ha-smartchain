import { escapeHtml } from "../services.js";

/**
 * <sc-validation-panel> — displays validation results (errors/warnings).
 *
 * Properties:
 *   .result = { valid: bool, errors: [...], warnings: [...] }
 */
export class ScValidationPanel extends HTMLElement {
  constructor() {
    super();
    this._result = null;
    this._rendered = false;
  }

  set result(val) {
    this._result = val;
    if (this._rendered) this._update();
  }

  connectedCallback() {
    if (!this._rendered) {
      this.innerHTML = `
        <style>
          .vp-wrap { margin-top: 12px; border-radius: 8px; overflow: hidden; border: 1px solid var(--divider-color, #e0e0e0); }
          .vp-header {
            padding: 10px 14px; font-size: 14px; font-weight: 500;
            display: flex; align-items: center; gap: 8px;
          }
          .vp-valid { background: color-mix(in srgb, var(--success-color, #4caf50) 15%, transparent); color: var(--success-color, #4caf50); }
          .vp-invalid { background: color-mix(in srgb, var(--error-color, #f44336) 15%, transparent); color: var(--error-color, #f44336); }
          .vp-list { padding: 0; margin: 0; list-style: none; }
          .vp-list li {
            padding: 6px 14px; font-size: 13px;
            border-top: 1px solid var(--divider-color, #e0e0e0);
            display: flex; align-items: flex-start; gap: 6px;
          }
          .vp-icon { flex-shrink: 0; font-size: 14px; }
          .vp-err .vp-icon { color: var(--error-color, #f44336); }
          .vp-warn .vp-icon { color: var(--warning-color, #ff9800); }
          .vp-hidden { display: none; }
        </style>
        <div class="vp-container vp-hidden"></div>
      `;
      this._rendered = true;
      if (this._result) this._update();
    }
  }

  _update() {
    const container = this.querySelector(".vp-container");
    if (!container) return;

    if (!this._result) {
      container.classList.add("vp-hidden");
      return;
    }

    const { valid, errors = [], warnings = [] } = this._result;
    let html = `<div class="vp-wrap">
      <div class="vp-header ${valid ? "vp-valid" : "vp-invalid"}">
        ${valid ? "&#10003;" : "&#10007;"} ${valid ? "Valid" : "Invalid"}
        \u2014 ${errors.length} error(s), ${warnings.length} warning(s)
      </div>`;

    if (errors.length || warnings.length) {
      html += `<ul class="vp-list">`;
      for (const err of errors) {
        html += `<li class="vp-err"><span class="vp-icon">&#10007;</span> ${escapeHtml(err)}</li>`;
      }
      for (const warn of warnings) {
        html += `<li class="vp-warn"><span class="vp-icon">&#9888;</span> ${escapeHtml(warn)}</li>`;
      }
      html += `</ul>`;
    }
    html += `</div>`;
    container.innerHTML = html;
    container.classList.remove("vp-hidden");
  }

  clear() {
    const container = this.querySelector(".vp-container");
    if (container) {
      container.classList.add("vp-hidden");
      container.innerHTML = "";
    }
    this._result = null;
  }
}

customElements.define("sc-validation-panel", ScValidationPanel);
