import { callWS, escapeHtml, showToast } from "../services.js";
// Same cache-busting query this module was loaded with — importing
// config-form.js both with and without `?v=` would instantiate it twice
// and the second customElements.define would throw.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
await import(`./config-form.js${_v ? `?v=${_v}` : ""}`);

const STORE_COMMANDS = {
  schema: "smartchain/store/schema",
  save: "smartchain/store/save",
};

/**
 * Said when `embeddings_available` comes back empty — the one state this form
 * cannot be filled in at all. The dropdown is required and has no options, so
 * there is no value to type; the only useful thing to say names the tab that
 * makes one. Shown before anything is pressed, with Save held, rather than
 * left for the backend to refuse afterwards.
 */
const NO_BINDINGS_NOTICE =
  "No embeddings binding exists yet, so this store has nothing to bind to. " +
  "Create one on the Embeddings tab first, then come back here.";

/**
 * <sc-stores-tab> — every memory and vector store on one screen.
 *
 * Stores used to be configurable only by editing the `memory:` block of
 * tools.yaml, which meant a pgvector connection string and a qdrant API key
 * sat in a text file the panel hands to the browser. A store is now a config
 * subentry, so those two never travel back out: the form accepts a key and
 * only ever hears `secrets_set` about it afterwards.
 *
 * Two things this tab must show that the embeddings tab does not:
 *
 *  - **Which stores are actually live.** MemoryRegistry contains a failing
 *    store so the others still start, which used to leave a dead store
 *    indistinguishable from a working one anywhere but the log.
 *    `smartchain/store/status` answers that, including for the stores that
 *    still live in tools.yaml and cannot be edited here.
 *  - **What is about to unbind.** A store resolves its embeddings binding by
 *    *title*; a title claimed twice resolves to nothing. The backend names
 *    those titles in `embeddings_ambiguous` and refuses to save one, so the
 *    warning lands before the write rather than after a store quietly stops
 *    answering.
 *  - **When there is nothing to bind to at all.** On a fresh install
 *    `embeddings_available` is empty, which makes the required `embeddings`
 *    dropdown unanswerable — the form is not merely blank, it cannot be
 *    filled in. That is said up front and Save is held (NO_BINDINGS_NOTICE),
 *    because the alternative is a user pressing Save into a refusal about a
 *    control they were never able to touch.
 *
 * The form itself is <sc-config-form> over a backend-serialised schema, like
 * every other tab — this file names `name` and `embeddings` only to phrase its
 * two confirmations, never to declare a field.
 *
 * Properties: .hass, .entries
 */
export class ScStoresTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._status = null; // {stores: [...], shadowed_yaml: [...]} once loaded
    this._editing = null; // {entryId, subentryId|null, originalTitle|null}
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    const form = this.querySelector("sc-config-form");
    if (form) form.hass = val;
    if (first) this._loadStatus();
  }

  set entries(val) {
    // Home Assistant pushes `hass` on every state change; the shell must not
    // turn that into a repaint. The overview array is a new object only when
    // it has actually been refetched.
    if (val === this._rawEntries) return;
    this._rawEntries = val;
    this._entries = val || [];
    if (!this._rendered) return;
    // Never rebuild out from under a form the user might be filling in —
    // same reasoning, and same `_editing` test, as the embeddings tab.
    if (this._editing) return;
    this._paint();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._paint();
    if (this._hass) this._loadStatus();
  }

  _requestRefresh() {
    this.dispatchEvent(new CustomEvent("sc-overview-refresh", { bubbles: true, composed: true }));
  }

  async _loadStatus() {
    if (!this._hass) return;
    try {
      this._status = await callWS(this._hass, "smartchain/store/status");
    } catch (err) {
      // A missing status costs the health block, not the tab.
      showToast(err.message || "Could not read store status", "error");
      this._status = null;
    }
    if (this._rendered && !this._editing) this._paint();
  }

  _render() {
    this.innerHTML = `<div class="sc-stores"></div>`;
  }

  _paint() {
    const root = this.querySelector(".sc-stores");
    if (!root) return;

    if (this._editing) {
      this._paintForm(root);
      return;
    }

    if (!this._entries.length) {
      root.innerHTML = `
        <p class="sc-empty">
          No SmartChain providers are configured yet.
          Add one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    root.innerHTML = `${this._statusHtml()}${this._entries
      .map((entry) => this._entryHtml(entry))
      .join("")}`;

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

  /**
   * The health block. It lists every *configured* store, including the ones
   * defined in tools.yaml that this tab cannot edit — a user whose store is
   * not working needs to be told so whichever file or dialog created it.
   */
  _statusHtml() {
    if (!this._status || !Array.isArray(this._status.stores)) return "";
    const rows = this._status.stores;
    const shadowed = this._status.shadowed_yaml || [];
    if (!rows.length && !shadowed.length) return "";

    const list = rows
      .map(
        (row) => `
        <li class="sc-store-status ${row.ok ? "sc-ok" : "sc-bad"}">
          <span class="sc-store-name">${escapeHtml(row.name)}</span>
          <span class="sc-store-origin">${escapeHtml(
            row.source === "yaml" ? "tools.yaml" : "configured here"
          )}${row.entity_index ? " · entity index" : ""}</span>
          <span class="sc-store-reason">${escapeHtml(
            row.ok ? "running" : row.reason || "not running"
          )}</span>
        </li>`
      )
      .join("");

    const warning = shadowed.length
      ? `<p class="sc-empty">Also defined in tools.yaml and ignored in favour of the store
          configured here: ${escapeHtml(shadowed.join(", "))}. Delete it from tools.yaml to
          silence this.</p>`
      : "";

    return `
      <section class="sc-entry">
        <header class="sc-entry-head"><span class="sc-entry-title">Store status</span></header>
        <ul class="sc-store-list">${list}</ul>
        ${warning}
      </section>`;
  }

  _entryHtml(entry) {
    const stores = entry.stores || [];
    return `
      <section class="sc-entry" data-entry="${escapeHtml(entry.entry_id)}">
        <header class="sc-entry-head">
          <span class="sc-entry-title">${escapeHtml(entry.title)}</span>
          <span class="sc-entry-engine">${escapeHtml(entry.engine_label)}</span>
          <button class="sc-add" data-entry="${escapeHtml(entry.entry_id)}">+ Store</button>
        </header>
        ${
          stores.length
            ? `<ul class="sc-embed-list">${stores
                .map(
                  (store) => `
              <li class="sc-embed-row">
                <span class="sc-embed-name">${escapeHtml(store.title)}${
                  store.ok ? "" : " ⚠"
                }</span>
                <span class="sc-embed-model">${escapeHtml(
                  // The reason a store is not running belongs on the store, not
                  // only in the health block above it.
                  `${store.backend_type} · ${store.embeddings || "unbound"}` +
                    (store.ok ? "" : ` · ${store.reason || "not running"}`)
                )}</span>
                <span class="sc-embed-actions">
                  <button data-act="edit" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(store.subentry_id)}">Edit</button>
                  <button data-act="del" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(store.subentry_id)}">Delete</button>
                </span>
              </li>`
                )
                .join("")}</ul>`
            : `<p class="sc-empty">No memory stores on this provider yet.</p>`
        }
      </section>`;
  }

  _paintForm(root) {
    root.innerHTML = `<div class="sc-store-notice"></div><sc-config-form></sc-config-form>`;
    const notice = root.querySelector(".sc-store-notice");
    const form = root.querySelector("sc-config-form");
    form.hass = this._hass;
    form.commands = STORE_COMMANDS;
    // A store form declares no model, so "Refresh models" would refresh
    // nothing it shows.
    form.showRefresh = false;
    // subentryId before entryId: config-form starts loading the moment
    // hass/commands/entryId are all set, so an Edit form's subentryId must
    // already be in place by then — otherwise it would load create-mode
    // defaults and silently discard the existing store.
    if (this._editing.subentryId) form.subentryId = this._editing.subentryId;
    form.entryId = this._editing.entryId;

    const originalTitle = this._editing.originalTitle;
    let ambiguous = [];
    let blocked = "";

    form.addEventListener("sc-loaded", (ev) => {
      const detail = ev.detail || {};
      ambiguous = detail.embeddings_ambiguous || [];
      // Re-read on every load, not just the first: `backend_type` is reactive,
      // so this form reloads its schema while it is open.
      blocked = this._blockedFor(detail.embeddings_available);
      notice.innerHTML = blocked
        ? `<p class="sc-empty sc-store-blocked">${escapeHtml(blocked)}</p>`
        : "";
      form.saveEnabled = !blocked;
    });

    form.addEventListener("sc-before-save", (ev) => {
      // Belt as well as braces: `saveEnabled` greys the button, this refuses
      // the save itself — a host that called `form.save()` for its own reasons
      // would otherwise walk straight past the notice.
      if (blocked) {
        ev.preventDefault();
        showToast(blocked, "error");
        return;
      }
      const data = (ev.detail && ev.detail.data) || {};
      const warning = this._warningFor(data, originalTitle, ambiguous);
      if (!warning) return;
      ev.preventDefault();
      if (confirm(warning)) form.save();
    });

    form.addEventListener("sc-saved", (ev) => {
      const detail = ev.detail || {};
      if (detail.reload_error) {
        showToast(`Saved, but the reload failed: ${detail.reload_error}`, "warning");
      } else if (detail.store_error) {
        // The subentry was written; the store it describes did not come up.
        // Without this the only word about it was a green "Saved".
        showToast(`Saved, but the store did not start: ${detail.store_error}`, "warning");
      } else if (detail.shadows_yaml) {
        showToast("Saved. A store of this name in tools.yaml is now ignored.", "warning");
      }
      this._editing = null;
      // Close the form immediately with whatever entries we already have —
      // the refetch below repaints again once genuinely fresh data lands.
      this._paint();
      this._requestRefresh();
      this._loadStatus();
    });
    form.addEventListener("sc-cancelled", () => {
      this._editing = null;
      this._paint();
    });
  }

  /**
   * Why this form cannot be submitted at all, or "" if it can.
   *
   * Only an explicitly empty list blocks. `undefined` — a backend that does
   * not send `embeddings_available` — means "unknown", and an unknown must
   * not disable a Save that would have worked.
   */
  _blockedFor(available) {
    if (!Array.isArray(available) || available.length) return "";
    return NO_BINDINGS_NOTICE;
  }

  /**
   * The one confirmation this tab owns, phrased from the two fields it
   * understands. Everything else the backend refuses outright.
   */
  _warningFor(data, originalTitle, ambiguous) {
    const nextTitle = data.name || "";
    if (originalTitle !== null && nextTitle !== originalTitle) {
      return (
        `Renaming "${originalTitle}" to "${nextTitle}" points the store at fresh, empty ` +
        `storage — the vectors already indexed stay under the old name and are not moved. ` +
        `Continue?`
      );
    }
    const binding = data.embeddings || "";
    if (binding && ambiguous.includes(binding)) {
      return (
        `"${binding}" is claimed by more than one embeddings binding, so it resolves to ` +
        `nothing and this store will not start. Save anyway?`
      );
    }
    return "";
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    const store = this._findStore(entryId, subentryId);

    if (act === "edit") {
      this._editing = { entryId, subentryId, originalTitle: store ? store.title : null };
      this._paint();
      return;
    }

    const label = store ? store.title : "this store";
    if (
      !confirm(
        `Delete "${label}"? The stored vectors are left where they are, so re-creating ` +
          `a store with the same name and backend finds them again.`
      )
    ) {
      return;
    }

    try {
      const result = await callWS(this._hass, "smartchain/store/delete", {
        entry_id: entryId,
        subentry_id: subentryId,
      });
      if (result && result.reload_error) {
        showToast(`Deleted, but the reload failed: ${result.reload_error}`, "warning");
      } else {
        showToast("Memory store deleted", "success");
      }
    } catch (err) {
      showToast(err.message || "That did not work", "error");
    }
    this._requestRefresh();
    this._loadStatus();
  }

  _findStore(entryId, subentryId) {
    const entry = this._entries.find((e) => e.entry_id === entryId);
    return entry && (entry.stores || []).find((store) => store.subentry_id === subentryId);
  }
}

customElements.define("sc-stores-tab", ScStoresTab);
