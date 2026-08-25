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
 * The binding list (with model and bound_stores) comes straight from
 * `smartchain/overview`'s `embeddings` field on each entry — the same single
 * source of truth agents-tab reads its agent list from, fetched once by the
 * shell and handed down via `.entries`. This tab asks for a fresh copy, by
 * dispatching `sc-overview-refresh`, after something it did changes it.
 *
 * Properties: .hass, .entries
 */
export class ScEmbeddingsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._editing = null; // {entryId, subentryId|null, originalTitle|null, originalBoundStores}
  }

  set hass(val) {
    this._hass = val;
    const form = this.querySelector("sc-config-form");
    if (form) form.hass = val;
  }

  set entries(val) {
    this._entries = (val || []).filter((entry) => entry.supports_embeddings);
    if (this._rendered) this._paint();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._paint();
  }

  _requestRefresh() {
    this.dispatchEvent(new CustomEvent("sc-overview-refresh", { bubbles: true, composed: true }));
  }

  _render() {
    this.innerHTML = `<div class="sc-embeddings"></div>`;
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

      // Seeded from the overview's own copy, then replaced with a fresh one
      // the moment the form's schema load resolves — the overview snapshot
      // could already be stale by the time this form opened.
      let boundStores = this._editing.originalBoundStores || [];
      const originalTitle = this._editing.originalTitle;

      // <sc-config-form> knows nothing about `bound_stores` — this tab is
      // the one place that interprets it.
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
        this._requestRefresh();
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
        const bindings = entry.embeddings || [];
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
                  <span class="sc-embed-model">${escapeHtml(binding.model || "—")}</span>
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
        this._editing = {
          entryId: button.dataset.entry,
          subentryId: null,
          originalTitle: null,
          originalBoundStores: [],
        };
        this._paint();
      })
    );

    root.querySelectorAll("[data-act]").forEach((button) =>
      button.addEventListener("click", () => this._act(button.dataset))
    );
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    const binding = this._findBinding(entryId, subentryId);

    if (act === "edit") {
      this._editing = {
        entryId,
        subentryId,
        originalTitle: binding ? binding.title : null,
        originalBoundStores: binding ? binding.bound_stores || [] : [],
      };
      this._paint();
      return;
    }

    // act === "del" — name what a delete would unbind before asking, not
    // after. The overview already carries `bound_stores` per binding, so no
    // extra round trip is needed just to show the warning.
    const label = binding ? binding.title : "this embeddings binding";
    const boundStores = binding ? binding.bound_stores || [] : [];
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
    this._requestRefresh();
  }

  _findBinding(entryId, subentryId) {
    const entry = this._entries.find((e) => e.entry_id === entryId);
    return entry && (entry.embeddings || []).find((binding) => binding.subentry_id === subentryId);
  }
}

customElements.define("sc-embeddings-tab", ScEmbeddingsTab);
