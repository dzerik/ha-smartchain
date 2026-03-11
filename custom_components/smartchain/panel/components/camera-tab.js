import { callService, extractResponse, getAgents, populateSelect } from "../services.js";

/**
 * <sc-camera-tab> — camera analysis tab.
 *
 * Properties:
 *   .hass = hass object
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
    // Agents
    const agents = getAgents(this._hass);
    populateSelect(this.querySelector("#ct-agent"), agents, "Auto (first available)");

    // Cameras
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
      <div class="sc-card">
        <h2>Analyze camera image</h2>
        <p>Select a camera and describe what you want the AI to look for.</p>

        <div class="sc-row">
          <div>
            <label class="sc-label">Agent</label>
            <select id="ct-agent" class="sc-select">
              <option value="">Auto (first available)</option>
            </select>
          </div>
          <div>
            <label class="sc-label">Camera</label>
            <select id="ct-camera" class="sc-select">
              <option value="">Select camera...</option>
            </select>
          </div>
        </div>

        <label class="sc-label">Question / Instruction</label>
        <textarea id="ct-prompt" class="sc-textarea"
          placeholder="What do you see? Is there anyone at the door? Describe the scene."></textarea>
        <div class="sc-btn-row">
          <button id="ct-btn-analyze" class="sc-btn sc-btn-primary">Analyze</button>
        </div>
      </div>

      <div id="ct-result" class="sc-hidden">
        <div class="sc-card">
          <h2>Analysis Result</h2>
          <div style="border:1px solid var(--divider-color,#e0e0e0);border-radius:8px;overflow:hidden;">
            <div style="padding:8px 12px;background:var(--primary-background-color,#fafafa);border-bottom:1px solid var(--divider-color,#e0e0e0);font-size:12px;color:var(--secondary-text-color);">Response</div>
            <pre id="ct-response" style="margin:0;padding:12px;font-family:var(--code-font-family,monospace);font-size:13px;line-height:1.5;white-space:pre-wrap;background:var(--code-editor-background-color,#1e1e1e);color:#d4d4d4;"></pre>
          </div>
        </div>
      </div>
    `;

    this.querySelector("#ct-btn-analyze").addEventListener("click", () => this._handleAnalyze());
  }

  async _handleAnalyze() {
    const camera = this.querySelector("#ct-camera").value;
    const prompt = this.querySelector("#ct-prompt").value.trim();
    if (!camera || !prompt) return;

    const agentId = this.querySelector("#ct-agent").value || undefined;

    const btn = this.querySelector("#ct-btn-analyze");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Analyzing...';
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
      }
    } catch (err) {
      this.querySelector("#ct-response").textContent = "Error: " + (err.message || err);
      this.querySelector("#ct-result").classList.remove("sc-hidden");
    } finally {
      btn.disabled = false;
      btn.textContent = "Analyze";
    }
  }
}

customElements.define("sc-camera-tab", ScCameraTab);
