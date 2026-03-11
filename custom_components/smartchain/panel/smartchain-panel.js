class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this._activeTab = "automations";
    this._loading = false;
    this._result = null;
    this._error = null;
    this._deployed = false;
    this._cameras = [];
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    this._updateCameras();
  }

  _updateCameras() {
    if (!this._hass) return;
    const cameras = [];
    for (const [entityId, state] of Object.entries(this._hass.states)) {
      if (entityId.startsWith("camera.") && state.state !== "unavailable") {
        cameras.push({
          id: entityId,
          name: state.attributes.friendly_name || entityId,
        });
      }
    }
    if (JSON.stringify(cameras) !== JSON.stringify(this._cameras)) {
      this._cameras = cameras;
      this._updateCameraSelect();
    }
  }

  _updateCameraSelect() {
    const select = this.querySelector("#camera-select");
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">Select camera...</option>';
    for (const cam of this._cameras) {
      const opt = document.createElement("option");
      opt.value = cam.id;
      opt.textContent = cam.name;
      select.appendChild(opt);
    }
    if (current) select.value = current;
  }

  async _callService(domain, service, data) {
    return await this._hass.connection.sendMessagePromise({
      type: "call_service",
      domain,
      service,
      service_data: data,
      return_response: true,
    });
  }

  _initialize() {
    this.innerHTML = `
      <style>
        :host { display: block; }
        .sc-container {
          max-width: 900px;
          margin: 0 auto;
          padding: 16px;
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
          color: var(--primary-text-color, #212121);
        }
        .sc-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 24px;
        }
        .sc-header h1 {
          margin: 0;
          font-size: 24px;
          font-weight: 400;
          color: var(--primary-text-color);
        }
        .sc-header ha-icon {
          color: var(--primary-color, #03a9f4);
          --mdc-icon-size: 32px;
        }
        .sc-tabs {
          display: flex;
          gap: 0;
          margin-bottom: 24px;
          border-bottom: 2px solid var(--divider-color, #e0e0e0);
        }
        .sc-tab {
          padding: 12px 24px;
          cursor: pointer;
          border: none;
          background: none;
          font-size: 14px;
          font-weight: 500;
          color: var(--secondary-text-color, #727272);
          border-bottom: 2px solid transparent;
          margin-bottom: -2px;
          transition: all 0.2s;
        }
        .sc-tab:hover { color: var(--primary-text-color); }
        .sc-tab.active {
          color: var(--primary-color, #03a9f4);
          border-bottom-color: var(--primary-color, #03a9f4);
        }
        .sc-card {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          padding: 24px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
          margin-bottom: 16px;
        }
        .sc-card h2 {
          margin: 0 0 8px 0;
          font-size: 18px;
          font-weight: 500;
        }
        .sc-card p {
          margin: 0 0 16px 0;
          color: var(--secondary-text-color);
          font-size: 14px;
        }
        .sc-textarea {
          width: 100%;
          min-height: 100px;
          padding: 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-family: inherit;
          font-size: 14px;
          resize: vertical;
          box-sizing: border-box;
        }
        .sc-textarea:focus {
          outline: none;
          border-color: var(--primary-color, #03a9f4);
        }
        .sc-select {
          width: 100%;
          padding: 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-size: 14px;
          margin-bottom: 12px;
        }
        .sc-btn-row { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
        .sc-btn {
          padding: 10px 24px;
          border: none;
          border-radius: 8px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }
        .sc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .sc-btn-primary {
          background: var(--primary-color, #03a9f4);
          color: #fff;
        }
        .sc-btn-primary:hover:not(:disabled) { filter: brightness(1.1); }
        .sc-btn-success {
          background: var(--success-color, #4caf50);
          color: #fff;
        }
        .sc-btn-success:hover:not(:disabled) { filter: brightness(1.1); }
        .sc-btn-outline {
          background: transparent;
          color: var(--primary-color, #03a9f4);
          border: 1px solid var(--primary-color, #03a9f4);
        }
        .sc-result {
          margin-top: 20px;
          padding: 16px;
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          border: 1px solid var(--divider-color, #e0e0e0);
        }
        .sc-result pre {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 13px;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          color: var(--primary-text-color);
        }
        .sc-status {
          margin-top: 12px;
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 14px;
        }
        .sc-status-success {
          background: var(--success-color, #4caf50);
          color: #fff;
        }
        .sc-status-error {
          background: var(--error-color, #f44336);
          color: #fff;
        }
        .sc-spinner {
          display: inline-block;
          width: 20px; height: 20px;
          border: 2px solid rgba(255,255,255,0.3);
          border-top-color: #fff;
          border-radius: 50%;
          animation: sc-spin 0.6s linear infinite;
          vertical-align: middle;
          margin-right: 8px;
        }
        @keyframes sc-spin { to { transform: rotate(360deg); } }
        .sc-label {
          display: block;
          font-size: 13px;
          font-weight: 500;
          color: var(--secondary-text-color);
          margin-bottom: 6px;
        }
        .sc-hidden { display: none !important; }
      </style>

      <div class="sc-container">
        <div class="sc-header">
          <ha-icon icon="mdi:robot"></ha-icon>
          <h1>SmartChain AI</h1>
        </div>

        <div class="sc-tabs">
          <button class="sc-tab active" data-tab="automations">Generate Automation</button>
          <button class="sc-tab" data-tab="camera">Analyze Camera</button>
        </div>

        <!-- Tab: Automations -->
        <div id="tab-automations">
          <div class="sc-card">
            <h2>Describe your automation</h2>
            <p>Write what you want in natural language. SmartChain will generate Home Assistant automation YAML.</p>
            <label class="sc-label">Description</label>
            <textarea id="auto-description" class="sc-textarea"
              placeholder="Turn on the coffee machine at 7:00 AM on weekdays if I'm home. On weekends at 9:00."></textarea>
            <div class="sc-btn-row">
              <button id="btn-generate" class="sc-btn sc-btn-primary">Generate</button>
            </div>
          </div>

          <div id="auto-result" class="sc-hidden">
            <div class="sc-card">
              <h2>Generated Automation</h2>
              <div class="sc-result">
                <pre id="auto-yaml"></pre>
              </div>
              <div class="sc-btn-row">
                <button id="btn-deploy" class="sc-btn sc-btn-success">Deploy to Home Assistant</button>
                <button id="btn-copy" class="sc-btn sc-btn-outline">Copy YAML</button>
              </div>
              <div id="auto-status"></div>
            </div>
          </div>
        </div>

        <!-- Tab: Camera -->
        <div id="tab-camera" class="sc-hidden">
          <div class="sc-card">
            <h2>Analyze camera image</h2>
            <p>Select a camera and describe what you want the AI to look for.</p>
            <label class="sc-label">Camera</label>
            <select id="camera-select" class="sc-select">
              <option value="">Select camera...</option>
            </select>
            <label class="sc-label">Question / Instruction</label>
            <textarea id="camera-prompt" class="sc-textarea"
              placeholder="What do you see? Is there anyone at the door? Describe the scene."></textarea>
            <div class="sc-btn-row">
              <button id="btn-analyze" class="sc-btn sc-btn-primary">Analyze</button>
            </div>
          </div>

          <div id="camera-result" class="sc-hidden">
            <div class="sc-card">
              <h2>Analysis Result</h2>
              <div class="sc-result">
                <pre id="camera-response"></pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    // Tab switching
    this.querySelectorAll(".sc-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        this.querySelectorAll(".sc-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        this._activeTab = tab.dataset.tab;
        this.querySelector("#tab-automations").classList.toggle("sc-hidden", this._activeTab !== "automations");
        this.querySelector("#tab-camera").classList.toggle("sc-hidden", this._activeTab !== "camera");
      });
    });

    // Generate button
    this.querySelector("#btn-generate").addEventListener("click", () => this._handleGenerate());
    this.querySelector("#btn-deploy").addEventListener("click", () => this._handleDeploy());
    this.querySelector("#btn-copy").addEventListener("click", () => this._handleCopy());
    this.querySelector("#btn-analyze").addEventListener("click", () => this._handleAnalyze());

    this._updateCameraSelect();
  }

  async _handleGenerate() {
    const desc = this.querySelector("#auto-description").value.trim();
    if (!desc) return;

    const btn = this.querySelector("#btn-generate");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Generating...';
    this.querySelector("#auto-result").classList.add("sc-hidden");
    this.querySelector("#auto-status").innerHTML = "";
    this._deployed = false;

    try {
      const resp = await this._callService("smartchain", "generate_automation", {
        description: desc,
      });
      const data = resp.response?.["smartchain.generate_automation"] || resp.response || {};
      const yaml = data.automation_yaml || "";
      if (data.error) {
        this._showAutoStatus(data.error, true);
      } else if (yaml) {
        this._generatedYaml = yaml;
        this.querySelector("#auto-yaml").textContent = yaml;
        this.querySelector("#auto-result").classList.remove("sc-hidden");
      }
    } catch (err) {
      this._showAutoStatus("Error: " + (err.message || err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Generate";
    }
  }

  async _handleDeploy() {
    if (!this._generatedYaml || this._deployed) return;

    const btn = this.querySelector("#btn-deploy");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Deploying...';

    try {
      const resp = await this._callService("smartchain", "deploy_automation", {
        automation_yaml: this._generatedYaml,
      });
      const data = resp.response?.["smartchain.deploy_automation"] || resp.response || {};
      if (data.deployed) {
        this._deployed = true;
        this._showAutoStatus(
          `Automation "${data.alias || "Unnamed"}" deployed successfully!`,
          false
        );
        btn.textContent = "Deployed!";
      } else if (data.error) {
        this._showAutoStatus(data.error, true);
        btn.disabled = false;
        btn.textContent = "Deploy to Home Assistant";
      }
    } catch (err) {
      this._showAutoStatus("Deploy failed: " + (err.message || err), true);
      btn.disabled = false;
      btn.textContent = "Deploy to Home Assistant";
    }
  }

  _handleCopy() {
    if (!this._generatedYaml) return;
    navigator.clipboard.writeText(this._generatedYaml).then(() => {
      const btn = this.querySelector("#btn-copy");
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy YAML"), 2000);
    });
  }

  async _handleAnalyze() {
    const camera = this.querySelector("#camera-select").value;
    const prompt = this.querySelector("#camera-prompt").value.trim();
    if (!camera || !prompt) return;

    const btn = this.querySelector("#btn-analyze");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Analyzing...';
    this.querySelector("#camera-result").classList.add("sc-hidden");

    try {
      const resp = await this._callService("smartchain", "analyze_image", {
        camera_entity_id: camera,
        message: prompt,
      });
      const data = resp.response?.["smartchain.analyze_image"] || resp.response || {};
      const response = data.response || "";
      if (response) {
        this.querySelector("#camera-response").textContent = response;
        this.querySelector("#camera-result").classList.remove("sc-hidden");
      }
    } catch (err) {
      this.querySelector("#camera-response").textContent = "Error: " + (err.message || err);
      this.querySelector("#camera-result").classList.remove("sc-hidden");
    } finally {
      btn.disabled = false;
      btn.textContent = "Analyze";
    }
  }

  _showAutoStatus(message, isError) {
    const el = this.querySelector("#auto-status");
    el.innerHTML = `<div class="sc-status ${isError ? "sc-status-error" : "sc-status-success"}">${message}</div>`;
  }
}

customElements.define("smartchain-panel", SmartChainPanel);
