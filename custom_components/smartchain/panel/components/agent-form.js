import { callWS, showToast } from "../services.js";

/**
 * <sc-agent-form> — renders the agent schema the backend serialises.
 *
 * The form's fields are never declared here. <ha-form> is Home Assistant's own
 * element and consumes exactly the payload the backend sends, so adding a field
 * to the config flow makes it appear here with no change to this file.
 *
 * Properties: .hass, .entryId, .subentryId
 */
export class ScAgentForm extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._schema = null;
    this._data = {};
  }

  set hass(val) {
    this._hass = val;
  }

  set entryId(val) {
    this._entryId = val;
  }

  set subentryId(val) {
    this._subentryId = val;
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this.load();
  }

  async load(refresh = false) {
    if (!this._hass || !this._entryId) return;
    const payload = { entry_id: this._entryId, refresh };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    const result = await callWS(this._hass, "smartchain/agent/schema", payload);
    this._schema = result.schema;
    this._data = result.data || {};
    this._apply();
  }

  _render() {
    this.innerHTML = `
      <style>
        .sc-form-actions { display: flex; gap: 8px; justify-content: flex-end; align-items: center; margin-top: 16px; }
        .sc-form-actions .sc-form-spacer { flex: 1; }
      </style>
      <ha-form></ha-form>
      <div class="sc-form-actions">
        <mwc-button id="sc-form-refresh">Refresh models</mwc-button>
        <span class="sc-form-spacer"></span>
        <mwc-button id="sc-form-cancel">Cancel</mwc-button>
        <mwc-button id="sc-form-save">Save</mwc-button>
      </div>
    `;
    this.querySelector("ha-form").addEventListener("value-changed", (ev) => {
      this._data = ev.detail.value;
    });

    this.querySelector("#sc-form-save").addEventListener("click", async () => {
      const payload = {
        entry_id: this._entryId,
        data: this._data,
      };
      if (this._subentryId) payload.subentry_id = this._subentryId;
      try {
        const result = await callWS(this._hass, "smartchain/agent/save", payload);
        showToast("Agent saved", "success");
        this.dispatchEvent(
          new CustomEvent("sc-saved", {
            detail: { subentryId: result.subentry_id },
            bubbles: true,
            composed: true,
          })
        );
      } catch (err) {
        // The backend never puts a credential in a message, so this is safe
        // to show as-is.
        showToast(err.message || "Could not save the agent", "error");
      }
    });

    this.querySelector("#sc-form-cancel").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("sc-cancelled", { bubbles: true, composed: true }));
    });

    this.querySelector("#sc-form-refresh").addEventListener("click", () => {
      this.load(true);
    });
  }

  _apply() {
    const form = this.querySelector("ha-form");
    if (!form || !this._schema) return;
    form.hass = this._hass;
    form.schema = this._schema;
    form.data = this._data;
    form.computeLabel = (field) => field.name;
  }
}

customElements.define("sc-agent-form", ScAgentForm);
