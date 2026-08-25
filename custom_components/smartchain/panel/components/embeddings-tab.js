import { callWS, escapeHtml, showToast } from "../services.js";
import "./config-form.js";

const EMBEDDINGS_COMMANDS = {
  schema: "smartchain/embeddings/schema",
  save: "smartchain/embeddings/save",
};

/**
 * <sc-embeddings-tab> — every embeddings binding on one screen, with create,
 * edit and delete.
 *
 * A memory store binds to an embeddings subentry *by its title*, so this tab
 * carries two hazards agents-tab does not: renaming a bound subentry
 * silently unbinds every store that resolved it by the old title, and a
 * title claimed by two subentries at once unbinds it too. The backend can
 * now report both — this tab's job is to ask before writing, never to
 * explain after the fact why a store quietly stopped working.
 *
 * There is no SmartChain-specific "list embeddings bindings" command, so the
 * binding list per entry comes from Home Assistant's own generic
 * `config_entries/subentries/list`, filtered to the embeddings type.
 *
 * The entry list itself (with `supports_embeddings`) is fetched once by the
 * shell and handed down via `.entries`.
 *
 * Properties: .hass, .entries
 */
export class ScEmbeddingsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._bindings = {}; // entry_id -> [{subentry_id, subentry_type, title, unique_id}]
    this._editing = null; // {entryId, subentryId|null, originalTitle|null}
    this._loadToken = 0;
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    const form = this.querySelector("sc-config-form");
    if (form) form.hass = val;
    if (this._rendered && first) this._loadBindings();
  }

  set entries(val) {
    this._entries = (val || []).filter((entry) => entry.supports_embeddings);
    if (this._rendered && this._hass) this._loadBindings();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass) this._loadBindings();
  }

  _render() {
    this.innerHTML = `<div class="sc-embeddings"></div>`;
  }

  async _loadBindings() {
    if (!this._hass) return;
    const token = ++this._loadToken;
    const bindings = {};
    try {
      for (const entry of this._entries) {
        const list = await callWS(this._hass, "config_entries/subentries/list", {
          entry_id: entry.entry_id,
        });
        bindings[entry.entry_id] = (list || []).filter(
          (subentry) => subentry.subentry_type === "embeddings"
        );
      }
    } catch (err) {
      showToast(err.message || "Could not load embeddings bindings", "error");
    }
    if (token !== this._loadToken) return; // superseded by a newer load
    this._bindings = bindings;
    this._paint();
  }

  _paint() {
    const root = this.querySelector(".sc-embeddings");
    if (!root) return;

    if (this._editing) {
      root.innerHTML = `<sc-config-form></sc-config-form>`;
      const form = root.querySelector("sc-config-form");
      form.hass = this._hass;
      form.commands = EMBEDDINGS_COMMANDS;
      form.entryId = this._editing.entryId;
      if (this._editing.subentryId) form.subentryId = this._editing.subentryId;

      let boundStores = [];
      const originalTitle = this._editing.originalTitle;

      // The schema load's response carries `bound_stores` — this tab is the
      // one place that knows what that field means, not <sc-config-form>.
      form.addEventListener("sc-loaded", (ev) => {
        boundStores = ev.detail.bound_stores || [];
      });

      form.addEventListener("sc-before-save", (ev) => {
        const nextTitle = (ev.detail.data && ev.detail.data.name) || "";
        const isRename = originalTitle !== null && nextTitle !== originalTitle;
        if (!isRename || !boundStores.length) return;
        ev.preventDefault();
        const names = boundStores.join(", ");
        const pronoun = boundStores.length > 1 ? "them" : "it";
        if (
          confirm(
            `"${originalTitle}" is bound to ${names}, which resolve it by title. ` +
              `Renaming it will unbind ${pronoun}. Continue?`
          )
        ) {
          form.save();
        }
      });

      form.addEventListener("sc-saved", () => {
        this._editing = null;
        this._loadBindings();
      });
      form.addEventListener("sc-cancelled", () => {
        this._editing = null;
        this._paint();
      });
      return;
    }

    if (!this._entries.length) {
      root.innerHTML = `
        <p class="sc-empty">
          No configured provider supports embeddings yet.
          Add or edit one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    root.innerHTML = this._entries
      .map((entry) => {
        const bindings = this._bindings[entry.entry_id] || [];
        return `
        <section class="sc-entry" data-entry="${escapeHtml(entry.entry_id)}">
          <header class="sc-entry-head">
            <span class="sc-entry-title">${escapeHtml(entry.title)}</span>
            <span class="sc-entry-engine">${escapeHtml(entry.engine_label)}</span>
            <button class="sc-add" data-entry="${escapeHtml(entry.entry_id)}">+ Embeddings</button>
          </header>
          ${
            bindings.length
              ? `<ul class="sc-embed-list">${bindings
                  .map(
                    (binding) => `
                <li class="sc-embed-row">
                  <span class="sc-embed-name">${escapeHtml(binding.title)}</span>
                  <span class="sc-embed-actions">
                    <button data-act="edit" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(binding.subentry_id)}">Edit</button>
                    <button data-act="del" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(binding.subentry_id)}">Delete</button>
                  </span>
                </li>`
                  )
                  .join("")}</ul>`
              : `<p class="sc-empty">No embeddings bindings on this provider yet.</p>`
          }
        </section>`;
      })
      .join("");

    root.querySelectorAll(".sc-add").forEach((button) =>
      button.addEventListener("click", () => {
        this._editing = { entryId: button.dataset.entry, subentryId: null, originalTitle: null };
        this._paint();
      })
    );

    root.querySelectorAll("[data-act]").forEach((button) =>
      button.addEventListener("click", () => this._act(button.dataset))
    );
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    if (act === "edit") {
      const binding = this._findBinding(entryId, subentryId);
      this._editing = { entryId, subentryId, originalTitle: binding ? binding.title : null };
      this._paint();
      return;
    }

    // act === "del" — name what a delete would unbind before asking, not after.
    const binding = this._findBinding(entryId, subentryId);
    const label = binding ? binding.title : "this embeddings binding";

    let boundStores = [];
    try {
      const schema = await callWS(this._hass, "smartchain/embeddings/schema", {
        entry_id: entryId,
        subentry_id: subentryId,
      });
      boundStores = schema.bound_stores || [];
    } catch (err) {
      // The warning could not be fetched — still let the user decide, just
      // without the names. This does not block the delete itself.
      showToast(err.message || "Could not check bound memory stores", "warning");
    }
    const warning = boundStores.length
      ? ` This will unbind the memory store(s) that resolve it by title: ${boundStores.join(", ")}.`
      : "";
    if (!confirm(`Delete "${label}"?${warning}`)) return;

    try {
      await callWS(this._hass, "smartchain/embeddings/delete", {
        entry_id: entryId,
        subentry_id: subentryId,
      });
      showToast("Embeddings binding deleted", "success");
    } catch (err) {
      showToast(err.message || "That did not work", "error");
    }
    this._loadBindings();
  }

  _findBinding(entryId, subentryId) {
    return (this._bindings[entryId] || []).find((binding) => binding.subentry_id === subentryId);
  }
}

customElements.define("sc-embeddings-tab", ScEmbeddingsTab);
