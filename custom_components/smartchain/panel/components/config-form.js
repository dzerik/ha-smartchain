import { callWS, showToast } from "../services.js";

/**
 * Structural equality for the values <ha-form> carries: primitives, arrays
 * (a multi-select such as "allowed tools") and plain objects. Used to tell a
 * real edit from <ha-form> re-emitting the value it already had — `!==` on two
 * freshly built objects is always true, so it would call every emission an
 * edit and every form dirty the moment it rendered.
 */
function sameValue(a, b) {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, i) => sameValue(item, b[i]));
  }
  if (a && b && typeof a === "object" && typeof b === "object") {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const key of keys) {
      if (!sameValue(a[key], b[key])) return false;
    }
    return true;
  }
  return false;
}

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
 * Read-only:  .hasUnsavedChanges — true between the first real edit and the
 *              save that stores it. A host tab surfaces this so the panel shell
 *              can ask before it replaces the tab's DOM.
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
    // True only while a save is in flight. A save is one round trip away from
    // creating a config subentry, so a second click during the first would
    // create a second agent — same title, same prompt, no way to tell which is
    // which. Same shape as `_setBusy` in <sc-tools-tab>.
    this._busy = false;
    // True from the first field the user actually changes until the save that
    // stores it. Deliberately *not* recomputed by comparing against the loaded
    // data: a reactive form re-fetches its schema mid-edit and the server
    // echoes the entered values back as `data`, so "differs from what the
    // server last sent" would quietly go false while the edit is still unsaved.
    // Cleared in exactly one place — a successful save.
    this._dirty = false;
    // True only while `_apply` is assigning to <ha-form>; see `_apply`.
    this._applying = false;
  }

  /**
   * Whether this form holds something the user would lose. Read by the host
   * tab, and through it by the panel shell before it replaces the DOM.
   */
  get hasUnsavedChanges() {
    return this._dirty;
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
    if (save) save.disabled = !this._saveEnabled || this._busy;
  }

  /**
   * Mark a save as in flight, or done. The button going grey is the visible
   * half — a button that still looks pressable while nothing happens is what
   * makes a user click it again in the first place.
   */
  _setBusy(busy) {
    this._busy = busy;
    this._syncActions();
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
      this._showLoadError(null);
      this._apply();
      this.dispatchEvent(
        new CustomEvent("sc-loaded", { detail: result, bubbles: true, composed: true })
      );
    } catch (err) {
      // Leave whatever schema/data we already had in place — a failed
      // refresh should not blank out a form the user was mid-edit on.
      const message = err.message || "Could not load the form";
      showToast(message, "error");
      // ...but if there is nothing in place, the toast is the *only* record of
      // what happened, and it fades. A form that never loaded renders nothing
      // at all — `_apply` returns early with no schema — and on the store, tool
      // and settings forms "Refresh models" is hidden, so `load()` had no
      // caller left. That is a dead rectangle with a Save button. Say what
      // failed, and put the retry where the user is looking.
      if (!this._schema) this._showLoadError(message);
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
    // Not a refusal being swallowed: the first save is still running and will
    // report whatever it reports. This drops only the duplicate submission.
    if (this._busy) return undefined;
    this._setBusy(true);
    try {
      return await this._save();
    } finally {
      this._setBusy(false);
    }
  }

  /** The save itself, wrapped by `save()`'s in-flight guard. */
  async _save() {
    const payload = { entry_id: this._entryId, data: this._data };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    try {
      const result = await callWS(this._hass, this._commands.save, payload);
      this._fieldErrors = null;
      // Stored: there is nothing left to lose to a tab click. The only place
      // this is cleared — a refused save leaves the form dirty, which is
      // exactly when the edit is most worth protecting.
      this._dirty = false;
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
        // The field error alone is not the report. On a form taller than the
        // viewport — an agent's prompt box is — the field carrying it is
        // usually off-screen, and the only thing the user observes is a Save
        // button that did nothing. Say it where they are looking, in the label
        // they can see on the field rather than the backend's field name, and
        // move the form to it.
        const named = fields.map((name) => (this._labels && this._labels[name]) || name).join(", ");
        showToast(`Not saved — ${named}: ${message}`, "error");
        this._scrollToFields();
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
   * Bring the form back into view after a refusal.
   *
   * The target is <ha-form> as a whole, not the offending row: <ha-form>
   * renders its fields inside its own shadow root and exposes no node per
   * field, so a per-row scroll would have to reach into another component's
   * internals — and would break silently the day Home Assistant reorganises
   * them. The whole form scrolling into view puts the error on screen, which is
   * the point; the toast says which field.
   *
   * `scrollIntoView` is guarded because jsdom does not implement it — and,
   * deliberately, so that a browser without it costs the scroll and not the
   * toast that has already been shown.
   */
  _scrollToFields() {
    const form = this.querySelector("ha-form");
    if (form && typeof form.scrollIntoView === "function") {
      form.scrollIntoView({ behavior: "smooth", block: "center" });
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
        .sc-form-error { display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
          padding: 12px; border-radius: 6px; margin-bottom: 12px;
          background: var(--error-color, #db4437); color: var(--text-primary-color, #fff); }
        .sc-form-error .sc-form-error-text { flex: 1; min-width: 12em; }
      </style>
      <div class="sc-form-error sc-hidden">
        <ha-icon icon="mdi:alert-circle"></ha-icon>
        <span class="sc-form-error-text"></span>
        <mwc-button id="sc-form-retry">Retry</mwc-button>
      </div>
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
      // Our own `form.data =` assignment coming back around is not an edit.
      if (this._applying) return;
      if (!sameValue(previous, this._data)) this._dirty = true;
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

    this.querySelector("#sc-form-retry").addEventListener("click", () => {
      this.load();
    });

    this._syncActions();
  }

  /**
   * Show — or clear — the "this form never loaded" banner.
   *
   * Only reached with a message when there is no schema at all, so it can never
   * cover a form the user is working in. The wording has to carry both halves:
   * what failed (the backend's own message, which never contains a credential)
   * and what to do about it, naming the control that is right there.
   */
  _showLoadError(message) {
    const box = this.querySelector(".sc-form-error");
    if (!box) return;
    box.classList.toggle("sc-hidden", !message);
    const text = box.querySelector(".sc-form-error-text");
    if (text) {
      text.textContent = message
        ? `This form could not be loaded: ${message}. Nothing has been changed — press Retry to load it again.`
        : "";
    }
  }

  async _trySave() {
    if (!this._saveEnabled || this._busy) return;
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
    // `form.data = …` below can come straight back as a value-changed. That is
    // this component talking to itself, not the user typing, so it must not
    // mark the form dirty — otherwise every form is dirty from the moment it
    // renders and the leave-confirmation becomes noise to click through.
    this._applying = true;
    try {
      this._applyTo(form);
    } finally {
      this._applying = false;
    }
  }

  _applyTo(form) {
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
