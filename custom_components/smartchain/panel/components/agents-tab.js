import { callWS, escapeHtml, showToast } from "../services.js";
// Same cache-busting query this module was loaded with — importing
// config-form.js both with and without `?v=` would instantiate it twice
// and the second customElements.define would throw.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
await import(`./config-form.js${_v ? `?v=${_v}` : ""}`);

const AGENT_COMMANDS = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };

// `source` values from tools/inventory.py. A built-in has to read as a
// different kind of thing from a tool the user wrote, or the list answers
// "which tools" without answering "which of these did I make".
const TOOL_SOURCE_LABELS = {
  assist: "Assist API",
  builtin: "built-in",
  yaml: "tools.yaml",
  subentry: "built here",
  mcp: "MCP",
};

// `reason` values from tools/inventory.py — why a tool the agent could have is
// not bound right now. A list of only the live tools would say what is on but
// never what is missing and why.
const TOOL_REASON_LABELS = {
  not_allowed: "not in this agent's allowed tools",
  no_siblings: "needs a second agent on this provider",
  no_memory_store: "needs a memory store",
  no_entity_store: "needs an entity store",
  assist_api: "tools come from Home Assistant's own exposed entities",
};

/**
 * <sc-agents-tab> — every agent on one screen, with create, edit,
 * duplicate and delete.
 *
 * Home Assistant's own pages can do all of this too; what they cannot do is
 * show every agent's provider, model and tools at once, or copy a tuned agent
 * in one click. That overview is why this tab exists.
 *
 * The tools cell expands into the agent's whole inventory — built-ins and
 * custom tools together, the ones that are off included, each saying why. It
 * is the only screen that answers "what can this agent actually do"; before
 * v5.4.0 the answer was spread across a picker that often did not render and
 * two switches elsewhere in the form.
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

  // No `hasUnsavedChanges` getter here on purpose. Everything this tab could
  // lose lives in the <sc-config-form> it hosts, and the panel shell reads that
  // form directly (see `_holdsUnsaved`) — for every tab, not just this one. A
  // getter here would be a second copy of the same answer, and the first one
  // stayed the *only* copy for four releases while four other tabs went
  // unguarded. A tab with state outside a form still adds a getter of its own.

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
                  <details class="sc-agent-tools" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">
                    <summary>${agent.tool_count} of ${agent.tool_total} tools</summary>
                    <div class="sc-tool-inventory">Loading&hellip;</div>
                  </details>
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

    root.querySelectorAll("details.sc-agent-tools").forEach((details) =>
      // Fetched on first open rather than with the overview: one round trip
      // per agent on every panel load would pay for a list almost nobody has
      // expanded. `_loaded` makes reopening free.
      details.addEventListener("toggle", () => {
        if (!details.open || details._loaded) return;
        details._loaded = true;
        this._loadInventory(details);
      })
    );
  }

  async _loadInventory(details) {
    const box = details.querySelector(".sc-tool-inventory");
    try {
      const result = await callWS(this._hass, "smartchain/agent/tools", {
        entry_id: details.dataset.entry,
        subentry_id: details.dataset.sub,
      });
      box.innerHTML = result.tools.length
        ? `<ul class="sc-tool-inventory-list">${result.tools
            .map(
              (tool) => `
              <li class="${tool.enabled ? "sc-tool-on" : "sc-tool-off"}">
                <code>${escapeHtml(tool.name)}</code>
                <span class="sc-tool-source">${escapeHtml(
                  TOOL_SOURCE_LABELS[tool.source] || tool.source
                )}</span>
                ${
                  tool.reason
                    ? `<span class="sc-tool-reason">${escapeHtml(
                        TOOL_REASON_LABELS[tool.reason] || tool.reason
                      )}</span>`
                    : ""
                }
              </li>`
            )
            .join("")}</ul>`
        : `<p class="sc-empty">This agent has no tools available.</p>`;
    } catch (err) {
      // Let a retry happen: a failed load must not leave "Loading…" forever.
      details._loaded = false;
      box.textContent = err.message || "Could not read this agent's tools";
    }
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
