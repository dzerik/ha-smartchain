import { escapeHtml } from "../services.js";
// Same cache-busting query this module was loaded with — importing
// config-form.js both with and without `?v=` would instantiate it twice
// and the second customElements.define would throw.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
await import(`./config-form.js${_v ? `?v=${_v}` : ""}`);

const SETTINGS_COMMANDS = {
  schema: "smartchain/settings/get",
  save: "smartchain/settings/save",
};

/**
 * <sc-settings-tab> — the entry's *connection* settings.
 *
 * An entry is a connection to a provider; the model, prompt, temperature and
 * tools belong to an agent and are edited on the Agents tab. Most providers
 * therefore have no connection settings at all — the backend says so with
 * `empty: true` and this tab prints a sentence instead of an empty form.
 *
 * With a single configured entry — the common case — the picker is skipped
 * entirely and the form is shown directly. With more than one, a simple
 * picker stands in front of it.
 *
 * The entry list itself is fetched once by the shell and handed down via
 * `.entries` — this tab never fetches the overview itself.
 *
 * Properties: .hass, .entries
 */
export class ScSettingsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._selected = null; // entry_id, only meaningful with more than one entry
  }

  set hass(val) {
    this._hass = val;
    const form = this.querySelector("sc-config-form");
    if (form) form.hass = val;
  }

  set entries(val) {
    // Home Assistant pushes `hass` on every state change; the shell must not
    // turn that into a repaint. The overview array is a new object only when
    // it has actually been refetched.
    if (val === this._rawEntries) return;
    this._rawEntries = val;
    this._entries = val || [];
    if (!this._rendered) return;
    // Never rebuild out from under the settings form the user might be
    // filling in — it goes stale until the form closes (Save re-renders the
    // form itself; there is no separate "editing" state to fall out of
    // here, since the form is shown any time there is a resolved entry).
    if (this.querySelector("sc-config-form")) return;
    this._paint();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._paint();
  }

  _render() {
    this.innerHTML = `<div class="sc-settings"></div>`;
  }

  _paint() {
    const root = this.querySelector(".sc-settings");
    if (!root) return;

    if (!this._entries.length) {
      root.innerHTML = `
        <p class="sc-empty">
          No SmartChain providers are configured yet.
          Add one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    const entryId =
      this._selected || (this._entries.length === 1 ? this._entries[0].entry_id : null);

    if (!entryId) {
      root.innerHTML = `
        <ul class="sc-entry-picker">
          ${this._entries
            .map(
              (entry) => `
            <li>
              <button class="sc-entry-pick" data-entry="${escapeHtml(entry.entry_id)}">
                <span class="sc-entry-title">${escapeHtml(entry.title)}</span>
                <span class="sc-entry-engine">${escapeHtml(entry.engine_label)}</span>
              </button>
            </li>`
            )
            .join("")}
        </ul>`;
      root.querySelectorAll("[data-entry]").forEach((button) =>
        button.addEventListener("click", () => {
          this._selected = button.dataset.entry;
          this._paint();
        })
      );
      return;
    }

    const entry = this._entries.find((candidate) => candidate.entry_id === entryId);
    root.innerHTML = `<sc-config-form class="sc-hidden"></sc-config-form>`;
    const form = root.querySelector("sc-config-form");
    // Whether this provider has any connection settings is only known once the
    // schema arrives, so the form starts hidden — showing it first and then
    // swapping it for the sentence would flash a stray pair of buttons.
    form.addEventListener("sc-loaded", (event) => {
      if (event.detail && event.detail.empty) {
        root.innerHTML = `
          <p class="sc-empty">
            ${escapeHtml(entry ? entry.engine_label : "This provider")} has no connection settings.
            Models, prompts and tools belong to an agent &mdash; add or edit one on the Agents tab.
          </p>`;
        return;
      }
      form.classList.remove("sc-hidden");
    });
    form.hass = this._hass;
    form.commands = SETTINGS_COMMANDS;
    // With a single entry there is no picker to cancel back to — hide the
    // control rather than leave it as a silent no-op.
    form.showCancel = this._entries.length > 1;
    // A connection form declares no model, so "Refresh models" would refresh
    // nothing it shows.
    form.showRefresh = false;
    form.entryId = entryId;
    form.addEventListener("sc-cancelled", () => {
      if (this._entries.length > 1) {
        this._selected = null;
        this._paint();
      }
    });
  }
}

customElements.define("sc-settings-tab", ScSettingsTab);
