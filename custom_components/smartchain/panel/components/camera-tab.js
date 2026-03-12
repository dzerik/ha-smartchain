import { callService, extractResponse, getAgents, populateSelect, showToast } from "../services.js";

/**
 * <sc-camera-tab> — Camera image analysis tab.
 *
 * Properties: .hass
 */
export class ScCameraTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._cameras = [];
  }

  set hass(val) {
    this._hass = val;
    if (this._rendered) this._refresh();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass) this._refresh();
  }

  _refresh() {
    const agents = getAgents(this._hass);
    populateSelect(this.querySelector("#ct-agent"), agents, "Auto (first available)");

    const cameras = [];
    for (const [entityId, state] of Object.entries(this._hass.states)) {
      if (entityId.startsWith("camera.") && state.state !== "unavailable") {
        cameras.push({ id: entityId, name: state.attributes.friendly_name || entityId });
      }
    }
    if (JSON.stringify(cameras) !== JSON.stringify(this._cameras)) {
      this._cameras = cameras;
      populateSelect(this.querySelector("#ct-camera"), cameras, "Select camera...");
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .ct-form { display: flex; flex-direction: column; gap: 16px; }
        .ct-result-card {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 12px;
          overflow: hidden;
        }
        .ct-result-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 16px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 13px;
          font-weight: 500;
          color: var(--secondary-text-color);
        }
        .ct-result-header ha-icon { --mdc-icon-size: 18px; }
        .ct-response {
          margin: 0;
          padding: 16px;
          font-family: var(--code-font-family, monospace);
          font-size: 13px;
          line-height: 1.6;
          white-space: pre-wrap;
          background: var(--code-editor-background-color, #1e1e1e);
          color: #d4d4d4;
        }
      </style>

      <div class="sc-card">
        <h2><ha-icon icon="mdi:camera" style="--mdc-icon-size:22px;vertical-align:middle;margin-right:6px;"></ha-icon>Analyze Camera Image</h2>
        <p>Select a camera and describe what you want the AI to look for.</p>

        <div class="ct-form">
          <div class="sc-row">
            <div>
              <label class="sc-label">Agent</label>
              <select id="ct-agent" class="sc-select"></select>
            </div>
            <div>
              <label class="sc-label">Camera</label>
              <select id="ct-camera" class="sc-select"></select>
            </div>
          </div>

          <div>
            <label class="sc-label">Question / Instruction</label>
            <textarea id="ct-prompt" class="sc-textarea"
              placeholder="What do you see? Is there anyone at the door? Describe the scene."></textarea>
          </div>

          <div>
            <button id="ct-btn-analyze" class="sc-btn sc-btn-primary">
              <ha-icon icon="mdi:image-search"></ha-icon> Analyze
            </button>
          </div>
        </div>
      </div>

      <div id="ct-result" class="sc-hidden">
        <div class="sc-card" style="padding:0;">
          <div class="ct-result-card">
            <div class="ct-result-header">
              <ha-icon icon="mdi:robot"></ha-icon>
              Analysis Result
            </div>
            <pre id="ct-response" class="ct-response"></pre>
          </div>
        </div>
      </div>
    `;

    this.querySelector("#ct-btn-analyze").addEventListener("click", () => this._handleAnalyze());
  }

  async _handleAnalyze() {
    const camera = this.querySelector("#ct-camera").value;
    const prompt = this.querySelector("#ct-prompt").value.trim();
    if (!camera || !prompt) {
      showToast("Please select a camera and enter a question", "warning");
      return;
    }

    const agentId = this.querySelector("#ct-agent").value || undefined;
    const btn = this.querySelector("#ct-btn-analyze");
    btn.disabled = true;
    const icon = btn.querySelector("ha-icon");
    icon.icon = "mdi:loading";
    const textNode = icon.nextSibling;
    if (textNode) textNode.textContent = " Analyzing...";
    this.querySelector("#ct-result").classList.add("sc-hidden");

    try {
      const svcData = { camera_entity_id: camera, message: prompt };
      if (agentId) svcData.entity_id = agentId;

      const resp = await callService(this._hass, "smartchain", "analyze_image", svcData);
      const data = extractResponse(resp, "smartchain.analyze_image");
      const response = data.response || "";
      if (response) {
        this.querySelector("#ct-response").textContent = response;
        this.querySelector("#ct-result").classList.remove("sc-hidden");
        showToast("Analysis complete", "success");
      }
    } catch (err) {
      this.querySelector("#ct-response").textContent = "Error: " + (err.message || err);
      this.querySelector("#ct-result").classList.remove("sc-hidden");
      showToast("Analysis failed", "error");
    } finally {
      btn.disabled = false;
      icon.icon = "mdi:image-search";
      if (textNode) textNode.textContent = " Analyze";
    }
  }
}

customElements.define("sc-camera-tab", ScCameraTab);
