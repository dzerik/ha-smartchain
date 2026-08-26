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
 * Properties: .hass, .commands ({schema, save}), .entryId, .subentryId,
 *             .showCancel (default true — a generic UI toggle, not a field),
 *             .showRefresh (default true — "Refresh models" is meaningless on
 *              a form whose schema has no model in it),
 *             .saveEnabled (default true — false when the host knows this form
 *              cannot be satisfied at all, e.g. a required dropdown whose
 *              options are empty. Still a generic toggle: this component is
 *              told, it does not work it out)
 *
 * Some forms change shape as they are filled in: a memory store on the qdrant
 * backend asks for different fields than one on sqlite. A schema command can
 * say so by returning `reactive: ["<field>", ...]`; when one of those fields
 * changes value this component re-requests the schema, passing the values
 * entered so far as `data`. The list of such fields comes from the backend
 * like everything else, so no field name is declared here either. A command
 * that returns no `reactive` key behaves exactly as before.
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
 *                    "invalid_data: <fields> — <reason>" message named, and
 *                    `message` is that reason on its own — both generically
 *                    parsed, never a hardcoded field. See `_parseError`.
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
    this._descriptions = {};
    this._fieldErrors = null;
    this._showCancel = true;
    this._showRefresh = true;
    this._saveEnabled = true;
    // Field names whose value changes the shape of the form — supplied by the
    // schema command, never known here. Empty for every command that does not
    // send one, which is what keeps this inert for the other tabs.
    this._reactive = [];
    // Guards the reload a reactive change triggers: `_apply` assigns
    // `form.data`, and an <ha-form> that answers that with its own
    // value-changed would otherwise start a reload loop.
    this._reloading = false;
    // Guards only the *automatic* load triggered by property arrival (see
    // _loadIfReady) — it does not affect explicit calls to load(), which is
    // how the Refresh control keeps working after the first load.
    this._loaded = false;
  }

  set hass(val) {
    this._hass = val;
    this._loadIfReady();
  }

  set commands(val) {
    // {schema: "smartchain/agent/schema", save: "smartchain/agent/save"}
    this._commands = val;
    this._loadIfReady();
  }

  set entryId(val) {
    this._entryId = val;
    this._loadIfReady();
  }

  set subentryId(val) {
    this._subentryId = val;
  }

  set showCancel(val) {
    this._showCancel = val !== false;
    this._syncActions();
  }

  set showRefresh(val) {
    this._showRefresh = val !== false;
    this._syncActions();
  }

  set saveEnabled(val) {
    this._saveEnabled = val !== false;
    this._syncActions();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._loadIfReady();
  }

  /**
   * `root.innerHTML = "<sc-config-form></sc-config-form>"` connects this
   * element synchronously, so connectedCallback can run before a host has
   * finished setting `.hass` / `.commands` / `.entryId` on the following
   * lines — at that point `load()` would silently no-op and nothing would
   * ever call it again, leaving the form permanently blank. Every property
   * a load actually depends on re-checks readiness here; whichever setter
   * happens to complete the set is the one that starts it. `.hass` also
   * arrives continuously afterward as Home Assistant ticks, so this must
   * fire the automatic load at most once per element — `_loaded` is that
   * gate. `.subentryId` deliberately does not participate: it is optional
   * (absent means "create"), so it cannot gate readiness, but hosts must
   * still set it before whichever of hass/commands/entryId completes the
   * three — otherwise an Edit form would load create-mode defaults.
   */
  _loadIfReady() {
    if (!this._rendered || !this._hass || !this._commands || !this._entryId) return;
    if (this._loaded) return;
    this._loaded = true;
    this.load();
  }

  _syncActions() {
    const cancel = this.querySelector("#sc-form-cancel");
    if (cancel) cancel.classList.toggle("sc-hidden", !this._showCancel);
    const refresh = this.querySelector("#sc-form-refresh");
    if (refresh) refresh.classList.toggle("sc-hidden", !this._showRefresh);
    // Disabled rather than hidden: a Save that vanished would read as "this
    // form has no Save", where a greyed one plus the host's notice reads as
    // "not until you do that first".
    const save = this.querySelector("#sc-form-save");
    if (save) save.disabled = !this._saveEnabled;
  }

  async load(refresh = false) {
    if (!this._hass || !this._entryId || !this._commands) return;
    const payload = { entry_id: this._entryId, refresh };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    // Only sent once the backend has said this form is reactive — a command
    // that does not declare `data` would reject it as an extra key.
    if (this._reactive.length) payload.data = this._data;
    this._reloading = true;
    try {
      const result = await callWS(this._hass, this._commands.schema, payload);
      this._schema = result.schema;
      this._data = this._merged(result, refresh);
      this._labels = result.labels || {};
      this._descriptions = result.descriptions || {};
      this._reactive = Array.isArray(result.reactive) ? result.reactive : [];
      this._fieldErrors = null;
      this._apply();
      this.dispatchEvent(
        new CustomEvent("sc-loaded", { detail: result, bubbles: true, composed: true })
      );
    } catch (err) {
      // Leave whatever schema/data we already had in place — a failed
      // refresh should not blank out a form the user was mid-edit on.
      showToast(err.message || "Could not load the form", "error");
    } finally {
      this._reloading = false;
    }
  }

  /**
   * What the form should hold after a schema response comes back.
   *
   * An automatic or reactive load is the server telling us what this form is;
   * it wins outright. A *refresh* is not — the user pressed "Refresh models"
   * on a form they have been typing into, and the values they entered are the
   * whole reason they are still on this screen. Overwriting them made the one
   * recovery from a stale model list cost the user their prompt, which is a
   * poor trade for a dropdown.
   *
   * Only fields the returned schema still declares are kept. The server prunes
   * values it no longer wants to hear about (a conditional field that has gone
   * out of schema), and putting one back would have the save rejected as an
   * extra key — so the edits survive without smuggling anything past the
   * server's own idea of the form.
   */
  _merged(result, refresh) {
    const served = result.data || {};
    if (!refresh) return served;
    const declared = new Set((result.schema || []).map((field) => field.name));
    const kept = {};
    for (const [name, value] of Object.entries(this._data || {})) {
      if (declared.has(name)) kept[name] = value;
    }
    return { ...served, ...kept };
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
      const raw = err.message || "Could not save";
      const { fields, text } = this._parseError(raw);
      const message = text || raw;
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
   * "invalid_data: field_one, field_two — human readable reason". This is a
   * generic protocol convention shared by every save command — not a
   * SmartChain field name — so parsing it here, and checking the result
   * against whichever fields *this* schema happens to declare, adds no
   * per-field knowledge to this component.
   *
   * Both halves after the code are optional. Older commands sent only the
   * field list, and a failure with no identifiable field sends neither; the
   * em dash separates them because a field name can never contain one, which
   * is what makes a reason containing commas safe to carry.
   *
   * Returning the reason separately, rather than showing the whole message,
   * is the difference between a `model` field labelled "select a model from
   * the list, or type a custom model name" and one labelled
   * "invalid_data: model, model_user — select a model…".
   */
  _parseError(message) {
    const match = /^invalid_data(?::\s*([^—]*?))?\s*(?:—\s*([\s\S]*))?$/.exec(message || "");
    if (!match) return { fields: [], text: null };
    const text = (match[2] || "").trim() || null;
    if (!Array.isArray(this._schema)) return { fields: [], text };
    const declared = new Set(this._schema.map((field) => field.name));
    const fields = (match[1] || "")
      .split(",")
      .map((name) => name.trim())
      .filter((name) => declared.has(name));
    return { fields, text };
  }

  /**
   * Did one of the backend-declared reactive fields actually change value?
   * <ha-form> fires value-changed on every keystroke, so comparing the whole
   * object would reload the form while the user types.
   */
  _reactiveChanged(previous, next) {
    return this._reactive.some((name) => (previous || {})[name] !== (next || {})[name]);
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
      const previous = this._data;
      this._data = ev.detail.value;
      // A field the backend named as reactive decides which other fields
      // exist, so the schema is asked for again rather than guessed at here.
      if (!this._reloading && this._reactiveChanged(previous, this._data)) this.load();
    });

    this.querySelector("#sc-form-save").addEventListener("click", () => this._trySave());

    this.querySelector("#sc-form-cancel").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("sc-cancelled", { bubbles: true, composed: true }));
    });

    this.querySelector("#sc-form-refresh").addEventListener("click", () => {
      this.load(true);
    });

    this._syncActions();
  }

  async _trySave() {
    if (!this._saveEnabled) return;
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
    // A field with no description falls back to an empty string, not the raw
    // name — unlike a missing label, missing helper text should just be
    // absent rather than echo something meaningless under the field.
    form.computeHelper = (field) => (this._descriptions && this._descriptions[field.name]) || "";
    form.computeError = (error) => error;
  }
}

customElements.define("sc-config-form", ScConfigForm);
