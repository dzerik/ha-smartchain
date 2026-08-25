import { callWS, escapeHtml, showToast } from "../services.js";
// Same cache-busting query this module was loaded with — importing
// config-form.js both with and without `?v=` would instantiate it twice
// and the second customElements.define would throw.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
await import(`./config-form.js${_v ? `?v=${_v}` : ""}`);

const AGENT_COMMANDS = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };

/**
 * <sc-agents-tab> — every agent on one screen, with create, edit,
 * duplicate and delete.
 *
 * Home Assistant's own pages can do all of this too; what they cannot do is
 * show every agent's provider, model and tool count at once, or copy a tuned
 * agent in one click. That overview is why this tab exists.
 *
 * The overview itself is fetched once by the shell and handed down via
 * `.entries` — this tab only asks for a fresh copy, by dispatching
 * `sc-overview-refresh`, after something it did changes it.
 *
 * Properties: .hass, .entries
 */
export class ScAgentsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._editing = null; // {entryId, subentryId|null}
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
    // Never rebuild out from under a form the user might be filling in.
    // `_editing` (not DOM presence) is the right test: `sc-saved` clears it
    // and repaints immediately itself, synchronously, before this setter's
    // async trigger (the overview refetch it also requests) ever fires —
    // checking DOM presence here instead would still see the old form
    // mounted at that moment and wrongly skip the repaint that puts the
    // list back.
    if (this._editing) return;
    this._paint();
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
    this.innerHTML = `<div class="sc-agents"></div>`;
  }

  _paint() {
    const root = this.querySelector(".sc-agents");

    if (this._editing) {
      root.innerHTML = `<sc-config-form></sc-config-form>`;
      const form = root.querySelector("sc-config-form");
      form.hass = this._hass;
      form.commands = AGENT_COMMANDS;
      // subentryId before entryId: config-form starts loading the moment
      // hass/commands/entryId are all set, so an Edit form's subentryId
      // must already be in place by then — otherwise it would load
      // create-mode defaults and silently discard the existing agent.
      if (this._editing.subentryId) form.subentryId = this._editing.subentryId;
      form.entryId = this._editing.entryId;
      form.addEventListener("sc-saved", () => {
        this._editing = null;
        // Close the form immediately with whatever entries we already have
        // — do not wait on the round trip _requestRefresh() also kicks off
        // for genuinely fresh data (which will repaint again once it lands).
        this._paint();
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
          No SmartChain providers are configured yet.
          Add one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    root.innerHTML = this._entries
      .map(
        (entry) => `
        <section class="sc-entry" data-entry="${escapeHtml(entry.entry_id)}">
          <header class="sc-entry-head">
            <span class="sc-entry-title">${escapeHtml(entry.title)}</span>
            <span class="sc-entry-engine">${escapeHtml(entry.engine_label)}</span>
            <button class="sc-add" data-entry="${escapeHtml(entry.entry_id)}">+ Agent</button>
          </header>
          ${
            entry.agents.length
              ? `<ul class="sc-agent-list">${entry.agents
                  .map(
                    (agent) => `
                <li class="sc-agent-row">
                  <span class="sc-agent-name">${escapeHtml(agent.title)}</span>
                  <span class="sc-agent-model">${escapeHtml(agent.model || "—")}</span>
                  <span class="sc-agent-tools">${
                    agent.tool_count === null ? "all tools" : `${agent.tool_count} tools`
                  }</span>
                  <span class="sc-agent-actions">
                    <button data-act="edit" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Edit</button>
                    <button data-act="copy" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Duplicate</button>
                    <button data-act="del" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Delete</button>
                  </span>
                </li>`
                  )
                  .join("")}</ul>`
              : `<p class="sc-empty">No agents on this provider yet.</p>`
          }
        </section>`
      )
      .join("");

    root.querySelectorAll(".sc-add").forEach((button) =>
      button.addEventListener("click", () => {
        this._editing = { entryId: button.dataset.entry, subentryId: null };
        this._paint();
      })
    );

    root.querySelectorAll("[data-act]").forEach((button) =>
      button.addEventListener("click", () => this._act(button.dataset))
    );
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    if (act === "edit") {
      this._editing = { entryId, subentryId };
      this._paint();
      return;
    }

    if (act === "del") {
      const agent = this._findAgent(entryId, subentryId);
      // Deleting an agent destroys a tuned prompt with no undo.
      if (!confirm(`Delete "${agent ? agent.title : "this agent"}"?`)) return;
    }

    const type = act === "copy" ? "smartchain/agent/duplicate" : "smartchain/agent/delete";
    try {
      await callWS(this._hass, type, { entry_id: entryId, subentry_id: subentryId });
      showToast(act === "copy" ? "Agent duplicated" : "Agent deleted", "success");
    } catch (err) {
      showToast(err.message || "That did not work", "error");
    }
    this._requestRefresh();
  }

  _findAgent(entryId, subentryId) {
    const entry = this._entries.find((e) => e.entry_id === entryId);
    return entry && entry.agents.find((a) => a.subentry_id === subentryId);
  }
}

customElements.define("sc-agents-tab", ScAgentsTab);
