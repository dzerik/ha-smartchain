import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";
import "./components/agent-form.js";

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
    const form = this.querySelector("sc-agent-form");
    if (form) form.hass = this._hass;
  }

  _initialize() {
    // Task 1 scaffolding only: there is no overview command yet (Task 2), so
    // the entry id can't be discovered from the panel itself. Read it from
    // the URL hash as a temporary way to exercise <sc-agent-form> in a
    // browser. Task 5 replaces this whole block with the real tab shell.
    const entryId = new URLSearchParams(location.hash.slice(1)).get("entry");
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      ${entryId ? `<sc-agent-form></sc-agent-form>` : ""}
      <div class="sc-camera-container">
        <sc-camera-tab></sc-camera-tab>
      </div>
    `;
    if (entryId) {
      const form = this.querySelector("sc-agent-form");
      form.entryId = entryId;
    } else {
      console.info(
        "SmartChain: no entry id in URL hash — open /smartchain#entry=<entry_id> to preview the agent form."
      );
    }
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
