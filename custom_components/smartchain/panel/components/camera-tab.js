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
          /* Both halves of the pair come from the theme. Home Assistant
             resolves --code-editor-background-color to the card background, so
             a literal light-grey ink here was ~1.3:1 on every light theme; and
             a literal dark background paired with a themed ink would fail the
             other way round when the theme leaves the code variable unset. */
          background: var(--code-editor-background-color, var(--card-background-color, #fff));
          color: var(--primary-text-color, #212121);
        }
      </style>

      <div class="sc-card">
        <h2><ha-icon icon="mdi:camera" style="--mdc-icon-size:22px;vertical-align:middle;margin-right:6px;"></ha-icon>Analyze Camera Image</h2>
        <p>Select a camera and describe what you want the AI to look for.</p>

        <div class="ct-form">
          <div class="sc-row">
            <div>
              <label class="sc-label" for="ct-agent">Agent</label>
              <select id="ct-agent" class="sc-select"></select>
            </div>
            <div>
              <label class="sc-label" for="ct-camera">Camera</label>
              <select id="ct-camera" class="sc-select"></select>
            </div>
          </div>

          <div>
            <label class="sc-label" for="ct-prompt">Question / Instruction</label>
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

      <!-- The result lands after an await, by which time focus has moved on;
           without a live region it is drawn but never announced. The region
           only works while it is on screen, which is _showResult's job:
           .sc-hidden is display:none, and nothing inside a display:none
           subtree reaches the accessibility tree for the region to announce. -->
      <div id="ct-result" class="sc-hidden" aria-live="polite">
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

  /**
   * Write `text` into the result pane, and make sure it is announced.
   *
   * The order is the whole point. `#ct-result` carries `aria-live`, but while
   * it holds `.sc-hidden` it is `display: none`, and a node in a display:none
   * subtree is not in the accessibility tree at all — a screen reader sees no
   * change to announce, so the attribute promises something that mechanically
   * cannot happen. Revealing first and writing second puts the change in a
   * region that is on screen.
   *
   * It is also why a run reveals the pane with a progress line instead of
   * hiding it: the region is then already live, and the result that follows is
   * an ordinary text change inside a visible region rather than a region
   * appearing and being written to in the same frame — which is the case
   * assistive technologies disagree about.
   */
  _showResult(text) {
    this.querySelector("#ct-result").classList.remove("sc-hidden");
    this.querySelector("#ct-response").textContent = text;
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
    // Clears the previous run's answer *and* brings the live region on screen
    // before there is anything to announce — see `_showResult`.
    this._showResult("Analyzing…");

    try {
      const svcData = { camera_entity_id: camera, message: prompt };
      if (agentId) svcData.entity_id = agentId;

      const resp = await callService(this._hass, "smartchain", "analyze_image", svcData);
      const data = extractResponse(resp, "smartchain.analyze_image");
      const response = data.response || "";
      if (response) {
        this._showResult(response);
        showToast("Analysis complete", "success");
      } else {
        // The call succeeded and carried no text. This used to leave the pane
        // hidden and say nothing at all, so the run looked like it had never
        // happened; now it would leave the progress line standing forever.
        // Either way the user learns nothing, so say what came back.
        this._showResult("The model returned no text for this image.");
        showToast("Analysis returned no text", "warning");
      }
    } catch (err) {
      this._showResult("Error: " + (err.message || err));
      showToast("Analysis failed", "error");
    } finally {
      btn.disabled = false;
      icon.icon = "mdi:image-search";
      if (textNode) textNode.textContent = " Analyze";
    }
  }
}

customElements.define("sc-camera-tab", ScCameraTab);
