import { callService, extractResponse, showToast } from "../services.js";

/**
 * <sc-toolbar> — Editor toolbar: validate, deploy, diff, copy.
 *
 * Properties: .hass, .title, .dirty, .diffActive, .currentType, .getYaml()
 * Events: "action" { action, result? }
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
    this._sideBySide = true;
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
    const bar = this.querySelector(".tb-diff-bar");
    if (bar) bar.classList.toggle("sc-hidden", !this._diffActive);
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
          gap: 8px;
          padding: 8px 16px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
          flex-wrap: wrap;
          min-height: 42px;
        }
        .tb-title-wrap {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-right: auto;
          min-width: 0;
        }
        .tb-title {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          color: var(--primary-text-color);
        }
        .tb-dirty {
          width: 9px; height: 9px;
          border-radius: 50%;
          background: var(--warning-color, #ff9800);
          flex-shrink: 0;
        }
        .tb-sep { width: 1px; height: 22px; background: var(--divider-color, #ddd); margin: 0 4px; }
        .tb-validation {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
          padding: 3px 10px;
          border-radius: 6px;
          font-weight: 500;
          transition: opacity 0.3s;
        }
        .tb-validation ha-icon { --mdc-icon-size: 14px; }
        .tb-validation-ok { background: color-mix(in srgb, var(--success-color) 15%, transparent); color: var(--success-color); }
        .tb-validation-err { background: color-mix(in srgb, var(--error-color) 15%, transparent); color: var(--error-color); }
        .tb-diff-bar {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 6px 16px;
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 6%, var(--primary-background-color, #fafafa));
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
          font-size: 13px;
        }
        .tb-diff-stats { font-weight: 500; color: var(--primary-text-color); }
        .tb-diff-stats .diff-add { color: var(--success-color, #4caf50); }
        .tb-diff-stats .diff-del { color: var(--error-color, #f44336); }
        .tb-diff-nav { display: flex; align-items: center; gap: 4px; }
        .tb-diff-actions { margin-left: auto; display: flex; gap: 8px; }
      </style>

      <div class="tb-wrap">
        <div class="tb-title-wrap">
          <span class="tb-title">Untitled</span>
          <span class="tb-dirty sc-hidden"></span>
        </div>
        <button class="sc-btn sc-btn-ghost tb-validate" title="Validate YAML (Ctrl+Shift+V)">
          <ha-icon icon="mdi:check-circle-outline"></ha-icon> Validate
        </button>
        <button class="sc-btn sc-btn-success tb-deploy" title="Deploy to HA (Ctrl+Shift+D)">
          <ha-icon icon="mdi:cloud-upload"></ha-icon> Deploy
        </button>
        <span class="tb-sep"></span>
        <button class="sc-btn sc-btn-icon tb-diff" title="Toggle diff (Ctrl+Shift+G)">
          <ha-icon icon="mdi:file-compare"></ha-icon>
        </button>
        <button class="sc-btn sc-btn-icon tb-copy" title="Copy YAML">
          <ha-icon icon="mdi:content-copy"></ha-icon>
        </button>
        <span class="tb-validation"></span>
      </div>

      <div class="tb-diff-bar sc-hidden">
        <span class="tb-diff-stats"></span>
        <div class="tb-diff-nav">
          <button class="sc-btn sc-btn-icon tb-diff-prev" title="Previous change">
            <ha-icon icon="mdi:chevron-up"></ha-icon>
          </button>
          <button class="sc-btn sc-btn-icon tb-diff-next" title="Next change">
            <ha-icon icon="mdi:chevron-down"></ha-icon>
          </button>
          <span class="tb-sep"></span>
          <button class="sc-btn sc-btn-icon tb-diff-mode" title="Toggle inline/side-by-side">
            <ha-icon icon="mdi:arrow-split-vertical"></ha-icon>
          </button>
        </div>
        <div class="tb-diff-actions">
          <button class="sc-btn sc-btn-success tb-diff-accept">
            <ha-icon icon="mdi:check"></ha-icon> Accept
          </button>
          <button class="sc-btn sc-btn-danger tb-diff-revert">
            <ha-icon icon="mdi:undo"></ha-icon> Revert
          </button>
        </div>
      </div>
    `;

    // Main toolbar
    this.querySelector(".tb-validate").addEventListener("click", () => this._handleValidate());
    this.querySelector(".tb-deploy").addEventListener("click", () => this._handleDeploy());
    this.querySelector(".tb-diff").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff" } }));
    });
    this.querySelector(".tb-copy").addEventListener("click", () => this._handleCopy());

    // Diff bar
    this.querySelector(".tb-diff-prev").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff-prev" } }));
    });
    this.querySelector(".tb-diff-next").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff-next" } }));
    });
    this.querySelector(".tb-diff-mode").addEventListener("click", () => {
      this._sideBySide = !this._sideBySide;
      const icon = this.querySelector(".tb-diff-mode ha-icon");
      icon.icon = this._sideBySide ? "mdi:arrow-split-vertical" : "mdi:arrow-collapse-horizontal";
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff-toggle-mode", sideBySide: this._sideBySide } }));
    });
    this.querySelector(".tb-diff-accept").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff-accept" } }));
    });
    this.querySelector(".tb-diff-revert").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("action", { detail: { action: "diff-revert" } }));
    });
  }

  async _handleValidate() {
    const yaml = this._getYaml();
    if (!yaml || !this._hass) return;

    const btn = this.querySelector(".tb-validate");
    btn.disabled = true;
    const btnIcon = btn.querySelector("ha-icon");
    const origIcon = btnIcon.icon;
    btnIcon.icon = "mdi:loading";

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
      btnIcon.icon = origIcon;
    }
  }

  async _handleDeploy() {
    const yaml = this._getYaml();
    if (!yaml || !this._hass || this._deployed) return;

    const btn = this.querySelector(".tb-deploy");
    btn.disabled = true;
    btn.querySelector("ha-icon").icon = "mdi:loading";

    try {
      const resp = await callService(this._hass, "smartchain", "deploy_automation", {
        automation_yaml: yaml,
        type: this._currentType,
      });
      const data = extractResponse(resp, "smartchain.deploy_automation");
      if (data.deployed) {
        this._deployed = true;
        btn.querySelector("ha-icon").icon = "mdi:check-circle";
        btn.querySelector("ha-icon").nextSibling.textContent = " Deployed!";
        showToast(`${this._currentType} deployed successfully`, "success");
        this.dispatchEvent(new CustomEvent("action", { detail: { action: "deploy", result: data } }));
      } else if (data.error) {
        btn.querySelector("ha-icon").icon = "mdi:cloud-upload";
        btn.disabled = false;
        showToast(data.error, "error", 5000);
        if (data.validation) this._showValidation(data.validation);
      }
    } catch (err) {
      btn.querySelector("ha-icon").icon = "mdi:cloud-upload";
      btn.disabled = false;
      showToast("Deploy failed: " + (err.message || err), "error", 5000);
    }
  }

  _handleCopy() {
    const yaml = this._getYaml();
    if (!yaml) return;
    navigator.clipboard.writeText(yaml).then(() => {
      showToast("YAML copied to clipboard", "info", 2000);
    });
  }

  _showValidation(data) {
    const el = this.querySelector(".tb-validation");
    if (!el) return;
    if (data.valid) {
      const warns = data.warnings?.length || 0;
      el.className = "tb-validation tb-validation-ok";
      el.innerHTML = `<ha-icon icon="mdi:check-circle"></ha-icon>${warns ? `Valid (${warns} warning${warns > 1 ? "s" : ""})` : "Valid"}`;
      showToast(warns ? `Valid with ${warns} warning(s)` : "YAML is valid", "success");
    } else {
      const errs = data.errors?.length || 0;
      el.className = "tb-validation tb-validation-err";
      el.innerHTML = `<ha-icon icon="mdi:alert-circle"></ha-icon>${errs} error${errs > 1 ? "s" : ""}`;
      showToast(`Validation failed: ${errs} error(s)`, "error", 5000);
    }
    setTimeout(() => { el.innerHTML = ""; el.className = "tb-validation"; }, 6000);
  }

  _updateDeployBtn() {
    const btn = this.querySelector(".tb-deploy");
    if (btn && !this._deployed) {
      btn.disabled = false;
      const icon = btn.querySelector("ha-icon");
      if (icon) icon.icon = "mdi:cloud-upload";
      const textNode = icon?.nextSibling;
      if (textNode) textNode.textContent = " Deploy";
    }
  }

  updateDiffStats(stats) {
    const el = this.querySelector(".tb-diff-stats");
    if (!el) return;
    if (!stats || stats.changes === 0) {
      el.textContent = "No changes";
      return;
    }
    el.innerHTML =
      `${stats.changes} change${stats.changes > 1 ? "s" : ""}: ` +
      `<span class="diff-add">+${stats.additions}</span> ` +
      `<span class="diff-del">-${stats.deletions}</span>`;
  }
}

customElements.define("sc-toolbar", ScToolbar);
