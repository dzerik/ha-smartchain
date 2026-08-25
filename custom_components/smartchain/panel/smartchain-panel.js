import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";
import "./components/agents-tab.js";

const TABS = [
  { id: "agents", label: "Agents", tag: "sc-agents-tab", adminOnly: true },
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
  }

  set panel(panel) {
    this._panel = panel;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    } else {
      this._refreshTabs();
    }
    this._propagateHass();
  }

  // `hass.user` can arrive after the first `hass` does, so a missing user
  // reads as non-admin — the tab list is recomputed on every later `hass`
  // update via `_refreshTabs`, so an admin who resolves late still gets
  // the Agents tab; a non-admin never sees it, even briefly.
  _isAdmin() {
    return !!(this._hass && this._hass.user && this._hass.user.is_admin);
  }

  _visibleTabList() {
    const admin = this._isAdmin();
    return TABS.filter((tab) => !tab.adminOnly || admin);
  }

  _propagateHass() {
    // Only the visible tab is in the DOM, so this reaches whichever it is.
    for (const tab of TABS) {
      const el = this.querySelector(tab.tag);
      if (el) el.hass = this._hass;
    }
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      <div class="sc-tabs" role="tablist"></div>
      <div class="sc-tab-body" role="tabpanel" id="${TAB_PANEL_ID}"></div>
    `;
    this.querySelector(".sc-tabs").addEventListener("keydown", (ev) => this._onTabKeydown(ev));
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
    this._propagateHass();
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
