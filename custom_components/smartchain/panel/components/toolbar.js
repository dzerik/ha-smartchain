import { callService, extractResponse, escapeHtml } from "../services.js";

/**
 * <sc-toolbar> — Editor toolbar with validate, deploy, diff toggle, copy, new.
 *
 * Properties:
 *   .hass
 *   .title — displayed filename/alias
 *   .dirty — unsaved changes indicator
 *   .diffActive — is diff view active
 *   .currentType — "automation" | "script" | "scene" | "blueprint"
 *   .getYaml() — function that returns current YAML from editor
 *
 * Events:
 *   "action" — { action: "validate"|"deploy"|"diff"|"copy"|"new", result? }
 */
export class ScToolbar extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._title = "";
    this._dirty = false;
    this._diffActive = false;
    this._currentType = "automation";
    this._getYaml = () => "";
    this._rendered = false;
    this._deployed = false;
  }

  set hass(val) { this._hass = val; }
  set title(val) {
    this._title = val || "";
    const el = this.querySelector(".tb-title");
    if (el) el.textContent = this._title || "Untitled";
  }
  set dirty(val) {
    this._dirty = !!val;
    const dot = this.querySelector(".tb-dirty");
    if (dot) dot.classList.toggle("sc-hidden", !this._dirty);
    this._deployed = false;
    this._updateDeployBtn();
  }
  set diffActive(val) {
    this._diffActive = !!val;
    const btn = this.querySelector(".tb-diff");
    if (btn) btn.classList.toggle("active", this._diffActive);
  }
  set currentType(val) { this._currentType = val || "automation"; }
  set getYaml(fn) { this._getYaml = fn; }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .tb-wrap {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
          flex-wrap: wrap;
          min-height: 38px;
        }
        .tb-title-wrap {
          display: flex;
          align-items: center;
          gap: 4px;
          margin-right: auto;
          min-width: 0;
        }
        .tb-title {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          color: var(--primary-text-color);
        }
        .tb-dirty {
          width: 8px; height: 8px;
          border-radius: 50%;
          background: var(--warning-color, #ff9800);
          flex-shrink: 0;
        }
        .tb-sep {
          width: 1px;
          height: 20px;
          background: var(--divider-color, #ddd);
          margin: 0 4px;
        }
        .tb-validation {
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 4px;
        }
        .tb-validation-ok { background: color-mix(in srgb, var(--success-color) 15%, transparent); color: var(--success-color); }
        .tb-validation-err { background: color-mix(in srgb, var(--error-color) 15%, transparent); color: var(--error-color); }
      </style>
      <div class="tb-wrap">
        <div class="tb-title-wrap">
          <span class="tb-title">Untitled</span>
          <span class="tb-dirty sc-hidden"></span>
        </div>
        <button class="sc-btn sc-btn-ghost tb-validate" title="Validate YAML">\u2713 Validate</button>
        <button class="sc-btn sc-btn-success tb-deploy" title="Deploy to HA">\u21E1 Deploy</button>
        <span class="tb-sep"></span>
        <button class="sc-btn sc-btn-icon tb-diff" title="Toggle diff view">\u2194</button>
        <button class="sc-btn sc-btn-icon tb-copy" title="Copy YAML">\uD83D\uDCCB</button>
        <span class="tb-validation"></span>
      </div>
    `;

    this.querySelector(".tb-validate").addEventListener("click", () => this._handleValidate());
    this.querySelector(".tb-deploy").addEventListener("click", () => this._handleDeploy());
    this.querySelector(".tb-diff").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff" } }));
    });
    this.querySelector(".tb-copy").addEventListener("click", () => this._handleCopy());
  }

  async _handleValidate() {
    const yaml = this._getYaml();
    if (!yaml || !this._hass) return;

    const btn = this.querySelector(".tb-validate");
    btn.disabled = true;
    btn.textContent = "...";

    try {
      const resp = await callService(this._hass, "smartchain", "validate_automation", {
        automation_yaml: yaml,
        type: this._currentType,
      });
      const data = extractResponse(resp, "smartchain.validate_automation");
      this._showValidation(data);
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "validate", result: data } }));
    } catch (err) {
      this._showValidation({ valid: false, errors: [String(err)], warnings: [] });
    } finally {
      btn.disabled = false;
      btn.textContent = "\u2713 Validate";
    }
  }

  async _handleDeploy() {
    const yaml = this._getYaml();
    if (!yaml || !this._hass || this._deployed) return;

    const btn = this.querySelector(".tb-deploy");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>';

    try {
      const resp = await callService(this._hass, "smartchain", "deploy_automation", {
        automation_yaml: yaml,
        type: this._currentType,
      });
      const data = extractResponse(resp, "smartchain.deploy_automation");
      if (data.deployed) {
        this._deployed = true;
        btn.textContent = "\u2713 Deployed!";
        this.dispatchEvent(new CustomEvent("action", { detail: { action: "deploy", result: data } }));
      } else if (data.error) {
        btn.textContent = "\u21E1 Deploy";
        btn.disabled = false;
        if (data.validation) this._showValidation(data.validation);
      }
    } catch (err) {
      btn.textContent = "\u21E1 Deploy";
      btn.disabled = false;
    }
  }

  _handleCopy() {
    const yaml = this._getYaml();
    if (!yaml) return;
    navigator.clipboard.writeText(yaml).then(() => {
      const btn = this.querySelector(".tb-copy");
      btn.textContent = "\u2713";
      setTimeout(() => (btn.textContent = "\uD83D\uDCCB"), 1500);
    });
  }

  _showValidation(data) {
    const el = this.querySelector(".tb-validation");
    if (!el) return;
    if (data.valid) {
      const warns = data.warnings?.length || 0;
      el.className = "tb-validation tb-validation-ok";
      el.textContent = warns ? `\u2713 Valid (${warns} warning${warns > 1 ? "s" : ""})` : "\u2713 Valid";
    } else {
      const errs = data.errors?.length || 0;
      el.className = "tb-validation tb-validation-err";
      el.textContent = `\u2717 ${errs} error${errs > 1 ? "s" : ""}`;
    }
    setTimeout(() => { el.textContent = ""; el.className = "tb-validation"; }, 5000);
  }

  _updateDeployBtn() {
    const btn = this.querySelector(".tb-deploy");
    if (btn && !this._deployed) {
      btn.disabled = false;
      btn.textContent = "\u21E1 Deploy";
    }
  }
}

customElements.define("sc-toolbar", ScToolbar);
