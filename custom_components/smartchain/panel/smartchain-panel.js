import { callWS, showToast } from "./services.js";
import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";
import "./components/agents-tab.js";
import "./components/settings-tab.js";
import "./components/embeddings-tab.js";
import "./components/tools-tab.js";

const TABS = [
  { id: "agents", label: "Agents", tag: "sc-agents-tab", adminOnly: true },
  {
    id: "embeddings",
    label: "Embeddings",
    tag: "sc-embeddings-tab",
    adminOnly: true,
    // Hidden entirely when no configured entry can embed — there would be
    // nothing this tab could ever let a user do.
    hiddenUnless: (overview) => overview.entries.some((entry) => entry.supports_embeddings),
  },
  { id: "settings", label: "Settings", tag: "sc-settings-tab", adminOnly: true },
  { id: "tools", label: "Tools", tag: "sc-tools-tab", adminOnly: true },
  { id: "camera", label: "Camera", tag: "sc-camera-tab" },
];

const TAB_PANEL_ID = "sc-tab-panel";

class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._initialized = false;
    this._active = null;
    this._visibleTabs = [];
    this._overview = { entries: [] };
  }

  set panel(panel) {
    this._panel = panel;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    } else {
      this._refreshTabs();
    }
    this._propagateHass();
    if (first) this._loadOverview();
  }

  // The overview (every SmartChain entry, its agents and its
  // supports_embeddings flag) is fetched exactly once here, not by each tab
  // that needs it — Agents, Embeddings and Settings all read it via
  // `.entries`. A tab that mutates it (agent create/edit/duplicate/delete)
  // asks for a fresh copy by dispatching `sc-overview-refresh` rather than
  // fetching it again itself.
  async _loadOverview() {
    try {
      this._overview = await callWS(this._hass, "smartchain/overview");
    } catch (err) {
      showToast(err.message || "Could not load the SmartChain overview", "error");
      this._overview = { entries: [] };
    }
    // Embeddings' visibility depends on this data resolving, so it goes
    // through the same recomputation as a late-resolving admin user rather
    // than a second mechanism.
    this._refreshTabs();
    // Entries actually changed here — this is the one place besides mounting
    // a tab where pushing them is warranted.
    this._propagateEntries();
  }

  // `hass.user` can arrive after the first `hass` does, so a missing user
  // reads as non-admin — the tab list is recomputed on every later `hass`
  // update via `_refreshTabs`, so an admin who resolves late still gets
  // the Agents tab; a non-admin never sees it, even briefly. The overview
  // fetch resolving late is the same shape of problem for Embeddings' extra
  // visibility condition.
  _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin);
  }

  _visibleTabList() {
    const admin = this._isAdmin();
    return TABS.filter((tab) => {
      if (tab.adminOnly && !admin) return false;
      if (tab.hiddenUnless && !tab.hiddenUnless(this._overview)) return false;
      return true;
    });
  }

  // Home Assistant calls `set hass` on this element on *every* state change
  // in the house — a burst of them when entities are added. `.hass` and
  // `.entries` used to be pushed together here, which meant that burst
  // repainted whichever tab was open on every single state change, and — far
  // worse — rebuilt an open Create/Edit form (destroying whatever the user
  // had typed) on every one too. `.hass` alone is cheap and each tab's own
  // setter only forwards it, so it stays pushed on every update; `.entries`
  // is split out into _propagateEntries and pushed only when it has a
  // reason to (see call sites).
  _propagateHass() {
    // Only the visible tab is in the DOM, so this reaches whichever it is.
    for (const tab of TABS) {
      const el = this.querySelector(tab.tag);
      if (el) el.hass = this._hass;
    }
  }

  _propagateEntries() {
    for (const tab of TABS) {
      const el = this.querySelector(tab.tag);
      if (el) el.entries = this._overview.entries;
    }
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      <div class="sc-tabs" role="tablist"></div>
      <div class="sc-tab-body" role="tabpanel" id="${TAB_PANEL_ID}"></div>
    `;
    this.querySelector(".sc-tabs").addEventListener("keydown", (ev) => this._onTabKeydown(ev));
    // A tab that mutates the overview (agent create/edit/duplicate/delete)
    // asks for a fresh copy this way — the shell stays the overview's one
    // owner rather than each tab re-fetching it independently.
    this.addEventListener("sc-overview-refresh", () => this._loadOverview());
    this._visibleTabs = this._visibleTabList();
    this._active = this._visibleTabs[0]?.id;
    this._buildBar();
    this._select(this._active);
  }

  _refreshTabs() {
    const next = this._visibleTabList();
    const changed =
      next.length !== this._visibleTabs.length ||
      next.some((tab, i) => tab.id !== this._visibleTabs[i].id);
    if (!changed) return;
    this._visibleTabs = next;
    if (!next.find((tab) => tab.id === this._active)) {
      this._active = next[0]?.id;
    }
    this._buildBar();
    this._select(this._active);
  }

  _buildBar() {
    const bar = this.querySelector(".sc-tabs");
    bar.innerHTML = "";
    for (const tab of this._visibleTabs) {
      const button = document.createElement("button");
      button.className = "sc-tab";
      button.textContent = tab.label;
      button.dataset.tabId = tab.id;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", TAB_PANEL_ID);
      button.addEventListener("click", () => this._select(tab.id));
      bar.appendChild(button);
    }
    this._syncBar();
  }

  _syncBar() {
    const bar = this.querySelector(".sc-tabs");
    for (const button of bar.children) {
      const active = button.dataset.tabId === this._active;
      button.classList.toggle("sc-tab-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.tabIndex = active ? 0 : -1;
    }
  }

  _onTabKeydown(ev) {
    if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
    ev.preventDefault();
    const ids = this._visibleTabs.map((tab) => tab.id);
    const idx = ids.indexOf(this._active);
    if (idx === -1) return;
    const delta = ev.key === "ArrowRight" ? 1 : -1;
    const nextId = ids[(idx + delta + ids.length) % ids.length];
    this._select(nextId);
    const bar = this.querySelector(".sc-tabs");
    const button = [...bar.children].find((b) => b.dataset.tabId === nextId);
    if (button) button.focus();
  }

  _select(id) {
    // Never select a tab that isn't in the currently visible list — the
    // list can shrink out from under `id` if admin status changes.
    if (!this._visibleTabs.find((tab) => tab.id === id)) {
      id = this._visibleTabs[0]?.id;
    }
    this._active = id;
    this._syncBar();
    const tab = this._visibleTabs.find((t) => t.id === id);
    const body = this.querySelector(".sc-tab-body");
    body.innerHTML = tab ? `<${tab.tag}></${tab.tag}>` : "";
    // A newly mounted tab has neither yet — this is the other legitimate
    // reason (besides a genuine overview refetch) to push .entries.
    this._propagateHass();
    this._propagateEntries();
  }
}

customElements.define("smartchain-panel", SmartChainPanel);

(() => {
  const scriptUrl = import.meta.url || "";
  const vMatch = scriptUrl.match(/[?&]v=([^&]+)/);
  const version = vMatch ? vMatch[1] : "unknown";
  console.info(
    `%c  SMARTCHAIN  %c  v${version}  `,
    "color: #fff; background: #03a9f4; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
    "color: #fff; background: #444; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
  );
})();
