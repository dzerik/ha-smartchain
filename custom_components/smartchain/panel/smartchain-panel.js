import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";

class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._initialized = false;
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
    const cam = this.querySelector("sc-camera-tab");
    if (cam) cam.hass = this._hass;
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      <div class="sc-camera-container">
        <sc-camera-tab></sc-camera-tab>
      </div>
    `;
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
