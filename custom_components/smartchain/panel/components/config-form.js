import { callWS, showToast } from "../services.js";

/**
 * <sc-config-form> — renders whatever schema the backend serialises.
 *
 * This component knows nothing about agents, settings or embeddings: no
 * SmartChain field name, no field type, no per-field logic. It takes a pair
 * of websocket command names (`.commands`) and an optional `.entryId` /
 * `.subentryId`, fetches a schema+data+labels payload, and renders it with
 * <ha-form> — Home Assistant's own element, which consumes exactly the
 * payload the backend sends. Adding a field to a config flow makes it appear
 * here with no change to this file.
 *
 * Properties: .hass, .commands ({schema, save}), .entryId, .subentryId
 *
 * Events:
 *   sc-loaded      — detail: the full schema-command result (schema, data,
 *                    labels, and whatever else that command returns, e.g.
 *                    embeddings' bound_stores/title_taken_by). Hosts that
 *                    need that extra data listen here rather than this
 *                    component special-casing any of it.
 *   sc-before-save — detail: {data}. Cancelable: a host can call
 *                    `event.preventDefault()` to hold off the actual save
 *                    (e.g. to confirm a rename first) and later call
 *                    `form.save()` itself once satisfied.
 *   sc-saved       — detail: the save-command result.
 *   sc-save-error  — detail: {message, fields}. `fields` is whichever
 *                    declared schema field names the backend's
 *                    "invalid_data: <fields>" message named, generically
 *                    parsed — never a hardcoded field.
 *   sc-cancelled   — the Cancel button was pressed.
 */
export class ScConfigForm extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._commands = null;
    this._schema = null;
    this._data = {};
    this._labels = {};
    this._fieldErrors = null;
  }

  set hass(val) {
    this._hass = val;
  }

  set commands(val) {
    // {schema: "smartchain/agent/schema", save: "smartchain/agent/save"}
    this._commands = val;
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
    if (!this._hass || !this._entryId || !this._commands) return;
    const payload = { entry_id: this._entryId, refresh };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    try {
      const result = await callWS(this._hass, this._commands.schema, payload);
      this._schema = result.schema;
      this._data = result.data || {};
      this._labels = result.labels || {};
      this._fieldErrors = null;
      this._apply();
      this.dispatchEvent(
        new CustomEvent("sc-loaded", { detail: result, bubbles: true, composed: true })
      );
    } catch (err) {
      // Leave whatever schema/data we already had in place — a failed
      // refresh should not blank out a form the user was mid-edit on.
      showToast(err.message || "Could not load the form", "error");
    }
  }

  /**
   * Perform the actual save. Public so a host that intercepted
   * `sc-before-save` can call it once its own confirmation is satisfied.
   */
  async save() {
    const payload = { entry_id: this._entryId, data: this._data };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    try {
      const result = await callWS(this._hass, this._commands.save, payload);
      this._fieldErrors = null;
      this._apply();
      showToast("Saved", "success");
      this.dispatchEvent(
        new CustomEvent("sc-saved", { detail: result, bubbles: true, composed: true })
      );
      return result;
    } catch (err) {
      // The backend never puts a credential in a message, so this is safe
      // to show as-is.
      const message = err.message || "Could not save";
      const fields = this._matchingFields(message);
      if (fields.length) {
        this._fieldErrors = Object.fromEntries(fields.map((f) => [f, message]));
        this._apply();
      } else {
        showToast(message, "error");
      }
      this.dispatchEvent(
        new CustomEvent("sc-save-error", {
          detail: { message, fields },
          bubbles: true,
          composed: true,
        })
      );
      return undefined;
    }
  }

  /**
   * Every save command reports a validation failure the same way:
   * "invalid_data: field_one, field_two". This is a generic protocol
   * convention shared by agent/save, settings/save and embeddings/save —
   * not a SmartChain field name — so parsing it here, and checking the
   * result against whichever fields *this* schema happens to declare, adds
   * no per-field knowledge to this component.
   */
  _matchingFields(message) {
    const match = /^invalid_data: (.+)$/.exec(message || "");
    if (!match || !Array.isArray(this._schema)) return [];
    const declared = new Set(this._schema.map((field) => field.name));
    return match[1]
      .split(",")
      .map((name) => name.trim())
      .filter((name) => declared.has(name));
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

    this.querySelector("#sc-form-save").addEventListener("click", () => this._trySave());

    this.querySelector("#sc-form-cancel").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("sc-cancelled", { bubbles: true, composed: true }));
    });

    this.querySelector("#sc-form-refresh").addEventListener("click", () => {
      this.load(true);
    });
  }

  async _trySave() {
    const proceed = this.dispatchEvent(
      new CustomEvent("sc-before-save", {
        detail: { data: this._data },
        bubbles: true,
        composed: true,
        cancelable: true,
      })
    );
    if (!proceed) return; // a listener called preventDefault() — it owns the rest of the flow
    await this.save();
  }

  _apply() {
    const form = this.querySelector("ha-form");
    if (!form || !this._schema) return;
    form.hass = this._hass;
    form.schema = this._schema;
    form.data = this._data;
    form.error = this._fieldErrors || undefined;
    // A field with no translation falls back to its raw name, so a field
    // added without one still renders.
    form.computeLabel = (field) => (this._labels && this._labels[field.name]) || field.name;
    form.computeError = (error) => error;
  }
}

customElements.define("sc-config-form", ScConfigForm);
