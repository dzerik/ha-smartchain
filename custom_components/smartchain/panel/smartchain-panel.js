import { SC_STYLES } from "./styles.js";
import "./components/generate-tab.js";
import "./components/camera-tab.js";

class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this._activeTab = "generate";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    // Propagate hass to child components
    const genTab = this.querySelector("sc-generate-tab");
    const camTab = this.querySelector("sc-camera-tab");
    if (genTab) genTab.hass = hass;
    if (camTab) camTab.hass = hass;
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      <div class="sc-container">
        <div class="sc-header">
          <ha-icon icon="mdi:robot"></ha-icon>
          <h1>SmartChain AI</h1>
        </div>

        <div class="sc-tabs">
          <button class="sc-tab active" data-tab="generate">Generate YAML</button>
          <button class="sc-tab" data-tab="camera">Analyze Camera</button>
        </div>

        <div id="tab-generate">
          <sc-generate-tab></sc-generate-tab>
        </div>
        <div id="tab-camera" class="sc-hidden">
          <sc-camera-tab></sc-camera-tab>
        </div>
      </div>
    `;

    this.querySelectorAll(".sc-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        this.querySelectorAll(".sc-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        this._activeTab = tab.dataset.tab;
        this.querySelector("#tab-generate").classList.toggle("sc-hidden", this._activeTab !== "generate");
        this.querySelector("#tab-camera").classList.toggle("sc-hidden", this._activeTab !== "camera");
      });
    });
  }
}

customElements.define("smartchain-panel", SmartChainPanel);
