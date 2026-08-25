import { callWS, escapeHtml, showToast } from "../services.js";

/**
 * <sc-tools-tab> — a read-only view of tools.yaml.
 *
 * The text is displayed, never edited: no contenteditable, no textarea a
 * user could type into and expect to save. Editing tools.yaml happens on
 * disk; this tab exists to see what is currently there, check it, and tell
 * the live registry to pick it up.
 *
 * `tools/get` may report `exists: false` (no file at all — the normal
 * first-run state, not an error) or `exists: true` with an `error` (the file
 * is there but unreadable) — the two are shown distinguishably.
 *
 * Properties: .hass
 */
export class ScToolsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._state = null; // {path, text, exists, error}
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    if (this._rendered && first) this.reload();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass) this.reload();
  }

  async reload() {
    try {
      this._state = await callWS(this._hass, "smartchain/tools/get");
    } catch (err) {
      showToast(err.message || "Could not load tools.yaml", "error");
      this._state = null;
    }
    this._paint();
  }

  _render() {
    this.innerHTML = `
      <div class="sc-tools">
        <header class="sc-tools-head">
          <span class="sc-tools-path"></span>
          <span class="sc-tools-spacer"></span>
          <mwc-button id="sc-tools-validate">Validate</mwc-button>
          <mwc-button id="sc-tools-reload">Reload</mwc-button>
        </header>
        <div class="sc-tools-body"></div>
      </div>
    `;
    this.querySelector("#sc-tools-validate").addEventListener("click", () => this._validate());
    this.querySelector("#sc-tools-reload").addEventListener("click", () => this._reloadRegistry());
  }

  _paint() {
    const path = this.querySelector(".sc-tools-path");
    const body = this.querySelector(".sc-tools-body");
    if (!path || !body) return;

    if (!this._state) {
      path.textContent = "";
      body.innerHTML = `<p class="sc-empty">Could not load tools.yaml.</p>`;
      return;
    }

    path.textContent = this._state.path || "";

    if (this._state.error) {
      body.innerHTML = `
        <p class="sc-tools-error">
          <ha-icon icon="mdi:alert-circle"></ha-icon>
          ${escapeHtml(this._state.error)}
        </p>`;
      return;
    }

    if (!this._state.exists) {
      body.innerHTML = `
        <p class="sc-empty">
          No tools.yaml yet at this path — that is the normal state until
          custom tools are configured, not an error.
        </p>`;
      return;
    }

    body.innerHTML = `<pre class="sc-tools-text">${escapeHtml(this._state.text)}</pre>`;
  }

  async _validate() {
    try {
      const result = await callWS(this._hass, "smartchain/tools/validate");
      if (result.valid) {
        showToast("tools.yaml is valid", "success");
      } else {
        showToast(`tools.yaml is invalid: ${result.error}`, "error");
      }
    } catch (err) {
      showToast(err.message || "Could not validate tools.yaml", "error");
    }
  }

  async _reloadRegistry() {
    try {
      const result = await callWS(this._hass, "smartchain/tools/reload");
      showToast(`Reloaded ${result.tools} tool(s)`, "success");
    } catch (err) {
      showToast(err.message || "Could not reload tools.yaml", "error");
      return;
    }
    // The file on disk may have changed since this tab last read it.
    this.reload();
  }
}

customElements.define("sc-tools-tab", ScToolsTab);
