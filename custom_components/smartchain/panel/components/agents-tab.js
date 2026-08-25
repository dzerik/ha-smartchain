import { callWS, escapeHtml, showToast } from "../services.js";
import "./agent-form.js";

/**
 * <sc-agents-tab> — every agent on one screen, with create, edit,
 * duplicate and delete.
 *
 * Home Assistant's own pages can do all of this too; what they cannot do is
 * show every agent's provider, model and tool count at once, or copy a tuned
 * agent in one click. That overview is why this tab exists.
 *
 * Properties: .hass
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
      const result = await callWS(this._hass, "smartchain/overview");
      this._entries = result.entries || [];
    } catch (err) {
      showToast(err.message || "Could not load agents", "error");
      this._entries = [];
    }
    this._paint();
  }

  _render() {
    this.innerHTML = `<div class="sc-agents"></div>`;
  }

  _paint() {
    const root = this.querySelector(".sc-agents");

    if (this._editing) {
      root.innerHTML = `<sc-agent-form></sc-agent-form>`;
      const form = root.querySelector("sc-agent-form");
      form.hass = this._hass;
      form.entryId = this._editing.entryId;
      if (this._editing.subentryId) form.subentryId = this._editing.subentryId;
      form.addEventListener("sc-saved", () => {
        this._editing = null;
        this.reload();
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
    this.reload();
  }

  _findAgent(entryId, subentryId) {
    const entry = this._entries.find((e) => e.entry_id === entryId);
    return entry && entry.agents.find((a) => a.subentry_id === subentryId);
  }
}

customElements.define("sc-agents-tab", ScAgentsTab);
