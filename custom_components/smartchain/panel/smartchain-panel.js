import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";
import "./components/agents-tab.js";

const TABS = [
  { id: "agents", label: "Agents", tag: "sc-agents-tab" },
  { id: "camera", label: "Camera", tag: "sc-camera-tab" },
];

class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._initialized = false;
    this._active = TABS[0].id;
  }

  set panel(panel) {
    this._panel = panel;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    this._propagateHass();
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
      <div class="sc-tab-body"></div>
    `;
    const bar = this.querySelector(".sc-tabs");
    for (const tab of TABS) {
      const button = document.createElement("button");
      button.className = "sc-tab";
      button.textContent = tab.label;
      button.setAttribute("role", "tab");
      button.addEventListener("click", () => this._select(tab.id));
      bar.appendChild(button);
    }
    this._select(this._active);
  }

  _select(id) {
    this._active = id;
    const tab = TABS.find((t) => t.id === id) || TABS[0];
    const bar = this.querySelector(".sc-tabs");
    [...bar.children].forEach((button, i) => {
      button.classList.toggle("sc-tab-active", TABS[i].id === id);
    });
    const body = this.querySelector(".sc-tab-body");
    body.innerHTML = `<${tab.tag}></${tab.tag}>`;
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
