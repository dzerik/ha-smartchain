import { callWS, showToast } from "./services.js";
import { SC_STYLES } from "./styles.js";

// Carry this module's own cache-busting query down to every component it
// pulls in. Home Assistant appends `?v=<version>.<digest>` to the panel's
// module_url; a static `import "./components/x.js"` would drop it, so the
// shell could be fresh while its components came from an old cache — which
// fails in ways that look like data problems, not caching.
//
// Every import of a given module must use the SAME query, always or never:
// ESM keys the module registry by URL, so importing one file both with and
// without `?v=` instantiates it twice, and the second `customElements.define`
// throws. `services.js` and `styles.js` above are imported without a query
// everywhere, which is equally consistent.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
const _q = _v ? `?v=${_v}` : "";
await Promise.all([
  import(`./components/camera-tab.js${_q}`),
  import(`./components/agents-tab.js${_q}`),
  import(`./components/settings-tab.js${_q}`),
  import(`./components/embeddings-tab.js${_q}`),
  import(`./components/stores-tab.js${_q}`),
  import(`./components/tools-tab.js${_q}`),
]);

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
  // No `hiddenUnless`, unlike Embeddings: a store binds to an embeddings
  // *title*, which may live on a different config entry, so any provider can
  // host one — and the tab is also where a store that failed to start says so.
  { id: "stores", label: "Stores", tag: "sc-stores-tab", adminOnly: true },
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
    this._onBeforeUnload = (ev) => this._guardUnload(ev);
  }

  // Home Assistant mounts and unmounts this element as the user moves around
  // its sidebar, so the listener is added and removed with the element rather
  // than once at module scope: one left behind would go on blocking unloads
  // for a panel that is no longer on screen.
  connectedCallback() {
    window.addEventListener("beforeunload", this._onBeforeUnload);
  }

  disconnectedCallback() {
    window.removeEventListener("beforeunload", this._onBeforeUnload);
  }

  /**
   * Which visible tab, if any, is holding something the user has not saved.
   *
   * Only the selected tab is in the DOM, so this examines at most one element.
   * A tab that has no such state — Camera — answers nothing and never produces
   * a question: a confirmation that appears on every navigation is one the user
   * learns to click through, which would cost the guarantee entirely.
   */
  _unsavedTab() {
    for (const tab of TABS) {
      const el = this.querySelector(tab.tag);
      if (el && this._holdsUnsaved(el)) return tab;
    }
    return null;
  }

  /**
   * Whether a mounted tab is holding an edit that replacing its DOM would lose.
   *
   * Two sources, on purpose:
   *
   *  - **The form.** Five of the six tabs put their whole editing surface in an
   *    <sc-config-form>, which already tracks its own dirtiness, so the shell
   *    reads it directly rather than each tab repeating the same getter. It
   *    used to be exactly that — one getter, on <sc-agents-tab> alone — which
   *    made this guard true for one tab in five while the docstring above
   *    described it as complete. A tab added tomorrow that hosts the form is
   *    covered without touching this file or that tab.
   *  - **The tab itself**, via an optional `hasUnsavedChanges` getter, for
   *    state that is not in a form: <sc-tools-tab>'s tools.yaml editor is a
   *    plain <textarea> whose unsaved text no <sc-config-form> knows about.
   *    A tab that exposes no such getter reads as `undefined` and contributes
   *    nothing.
   */
  _holdsUnsaved(el) {
    if (el.hasUnsavedChanges) return true;
    return [...el.querySelectorAll("sc-config-form")].some((form) => form.hasUnsavedChanges);
  }

  /** True if it is all right to replace the tab body now. */
  _confirmLeave() {
    const tab = this._unsavedTab();
    if (!tab) return true;
    return confirm(
      `The ${tab.label} tab has unsaved changes.\n\n` +
        "Leave it anyway? What you have entered there will be lost."
    );
  }

  // The browser's own leave prompt, for the routes this element never sees:
  // closing the tab, reloading, following a link out of Home Assistant.
  // Browsers show their own wording; `preventDefault` is what asks at all.
  _guardUnload(ev) {
    if (!this._unsavedTab()) return;
    ev.preventDefault();
    // Still required by Chrome and Safari to trigger the dialog.
    ev.returnValue = "";
  }

  set panel(panel) {
    this._panel = panel;
    // Read from the panel config rather than a constant in this file, so what
    // it shows is the version actually installed — which is the point of
    // showing it at all.
    this._version = (panel && panel.config && panel.config.version) || "";
    this._paintVersion();
  }

  _paintVersion() {
    const slot = this.querySelector(".sc-version");
    if (slot) slot.textContent = this._version ? `v${this._version}` : "";
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
      <div class="sc-tabs-row">
        <div class="sc-tabs" role="tablist"></div>
        <span class="sc-version" title="Installed SmartChain version"></span>
      </div>
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
    this._paintVersion();
    this._select(this._active);
  }

  _refreshTabs() {
    const next = this._visibleTabList();
    const changed =
      next.length !== this._visibleTabs.length ||
      next.some((tab, i) => tab.id !== this._visibleTabs[i].id);
    if (!changed) return;
    this._visibleTabs = next;
    // The open tab disappearing (admin status resolving to false, Embeddings
    // going away with its last capable entry) is not navigation the user chose,
    // so it is not theirs to decline: leaving them on a tab that is no longer
    // visible would be worse than the lost edit. Every other case re-selects
    // the tab already open, which `_select` now recognises and leaves alone.
    const dropped = !next.find((tab) => tab.id === this._active);
    if (dropped) this._active = next[0]?.id;
    this._buildBar();
    this._select(this._active, { force: dropped });
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
    // The move can be declined (unsaved changes). Focus follows the selection,
    // so when the selection did not move, focus must not either — otherwise it
    // sits on a button that is not the selected tab and the next arrow key
    // counts from the wrong place.
    if (this._active !== nextId) return;
    const bar = this.querySelector(".sc-tabs");
    const button = [...bar.children].find((b) => b.dataset.tabId === nextId);
    if (button) button.focus();
  }

  _select(id, { force = false } = {}) {
    // Never select a tab that isn't in the currently visible list — the
    // list can shrink out from under `id` if admin status changes.
    if (!this._visibleTabs.find((tab) => tab.id === id)) {
      id = this._visibleTabs[0]?.id;
    }
    const tab = this._visibleTabs.find((t) => t.id === id);
    const mounted = tab ? this.querySelector(tab.tag) : null;
    // Selecting the tab that is already on screen: there is nothing to do, and
    // rebuilding it was the cheapest way to lose a half-filled form — a stray
    // click on the current tab, or any recomputation of the tab list.
    if (id === this._active && mounted) {
      this._syncBar();
      return;
    }
    // Past this point the tab body is destroyed, so this is the last moment to
    // ask. Declining leaves `_active` untouched — the bar is re-synced so it
    // keeps agreeing with what is actually on screen.
    if (!force && !this._confirmLeave()) {
      this._syncBar();
      return;
    }
    this._active = id;
    this._syncBar();
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
