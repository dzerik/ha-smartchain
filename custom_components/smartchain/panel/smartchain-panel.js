class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this._activeTab = "automations";
    this._deployed = false;
    this._cameras = [];
    this._agents = [];
    this._selectedEntities = [];
    this._allEntities = [];
    this._entityFilter = "";
    this._generatedYaml = "";
    this._validationResult = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    this._updateCameras();
    this._updateAgents();
    this._updateAllEntities();
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
      this._updateSelectOptions("#camera-select", this._cameras, "Select camera...");
    }
  }

  _updateAgents() {
    if (!this._hass) return;
    const agents = [];
    for (const [entityId, state] of Object.entries(this._hass.states)) {
      if (entityId.startsWith("conversation.") && entityId.includes("smartchain")) {
        agents.push({
          id: entityId,
          name: state.attributes.friendly_name || entityId,
        });
      }
    }
    if (JSON.stringify(agents) !== JSON.stringify(this._agents)) {
      this._agents = agents;
      this._updateSelectOptions("#agent-select-auto", this._agents, "Auto (first available)");
      this._updateSelectOptions("#agent-select-camera", this._agents, "Auto (first available)");
    }
  }

  _updateAllEntities() {
    if (!this._hass) return;
    const entities = [];
    for (const [entityId, state] of Object.entries(this._hass.states)) {
      if (state.state === "unavailable") continue;
      entities.push({
        id: entityId,
        name: state.attributes.friendly_name || entityId,
        domain: entityId.split(".")[0],
        state: state.state,
      });
    }
    entities.sort((a, b) => a.domain.localeCompare(b.domain) || a.id.localeCompare(b.id));
    this._allEntities = entities;
  }

  _updateSelectOptions(selector, items, placeholder) {
    const select = this.querySelector(selector);
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${placeholder}</option>`;
    for (const item of items) {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = item.name;
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
          max-width: 960px;
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
          padding: 10px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-size: 14px;
          margin-bottom: 12px;
        }
        .sc-row { display: flex; gap: 12px; margin-bottom: 12px; }
        .sc-row > * { flex: 1; }
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
        .sc-btn-outline:hover:not(:disabled) { background: var(--primary-color, #03a9f4); color: #fff; }
        .sc-btn-warn {
          background: var(--warning-color, #ff9800);
          color: #fff;
        }
        .sc-btn-warn:hover:not(:disabled) { filter: brightness(1.1); }

        /* Entity Picker */
        .sc-entity-picker { position: relative; margin-bottom: 12px; }
        .sc-entity-search {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-size: 14px;
          box-sizing: border-box;
        }
        .sc-entity-search:focus { outline: none; border-color: var(--primary-color, #03a9f4); }
        .sc-entity-dropdown {
          position: absolute;
          top: 100%;
          left: 0; right: 0;
          max-height: 240px;
          overflow-y: auto;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 0 0 8px 8px;
          z-index: 100;
          box-shadow: 0 4px 12px rgba(0,0,0,0.15);
          display: none;
        }
        .sc-entity-dropdown.open { display: block; }
        .sc-entity-item {
          padding: 8px 12px;
          cursor: pointer;
          font-size: 13px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .sc-entity-item:last-child { border-bottom: none; }
        .sc-entity-item:hover { background: var(--primary-background-color, #f5f5f5); }
        .sc-entity-item.selected { background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent); }
        .sc-entity-item-id { font-family: var(--code-font-family, monospace); color: var(--secondary-text-color); font-size: 12px; }
        .sc-entity-item-name { font-weight: 500; }
        .sc-entity-domain {
          padding: 6px 12px;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          color: var(--secondary-text-color);
          background: var(--primary-background-color, #fafafa);
          position: sticky;
          top: 0;
        }

        /* Chips */
        .sc-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; min-height: 0; }
        .sc-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border-radius: 16px;
          font-size: 12px;
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 15%, transparent);
          color: var(--primary-color, #03a9f4);
          font-weight: 500;
        }
        .sc-chip-remove {
          cursor: pointer;
          font-size: 14px;
          line-height: 1;
          opacity: 0.7;
        }
        .sc-chip-remove:hover { opacity: 1; }

        /* YAML Editor */
        .sc-yaml-editor {
          position: relative;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          overflow: hidden;
          margin-top: 12px;
        }
        .sc-yaml-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .sc-yaml-header-actions { display: flex; gap: 8px; align-items: center; }
        .sc-yaml-body {
          display: flex;
          max-height: 500px;
          overflow: auto;
          background: var(--code-editor-background-color, #1e1e1e);
        }
        .sc-line-numbers {
          padding: 12px 8px 12px 12px;
          text-align: right;
          user-select: none;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #858585;
          min-width: 32px;
          flex-shrink: 0;
        }
        .sc-yaml-content {
          flex: 1;
          padding: 12px 12px 12px 8px;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #d4d4d4;
          white-space: pre;
          overflow-x: auto;
        }
        .sc-yaml-textarea {
          flex: 1;
          padding: 12px 12px 12px 8px;
          font-family: var(--code-font-family, 'Roboto Mono', monospace);
          font-size: 13px;
          line-height: 1.5;
          color: #d4d4d4;
          background: transparent;
          border: none;
          outline: none;
          resize: none;
          min-height: 200px;
          white-space: pre;
          overflow-x: auto;
          tab-size: 2;
        }
        /* Syntax highlighting */
        .sc-hl-key { color: #9cdcfe; }
        .sc-hl-string { color: #ce9178; }
        .sc-hl-number { color: #b5cea8; }
        .sc-hl-bool { color: #569cd6; }
        .sc-hl-comment { color: #6a9955; font-style: italic; }
        .sc-hl-entity { color: #4ec9b0; }

        /* Validation */
        .sc-validation {
          margin-top: 12px;
          border-radius: 8px;
          overflow: hidden;
          border: 1px solid var(--divider-color, #e0e0e0);
        }
        .sc-val-header {
          padding: 10px 14px;
          font-size: 14px;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .sc-val-valid { background: color-mix(in srgb, var(--success-color, #4caf50) 15%, transparent); color: var(--success-color, #4caf50); }
        .sc-val-invalid { background: color-mix(in srgb, var(--error-color, #f44336) 15%, transparent); color: var(--error-color, #f44336); }
        .sc-val-list {
          padding: 0;
          margin: 0;
          list-style: none;
        }
        .sc-val-list li {
          padding: 6px 14px;
          font-size: 13px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          display: flex;
          align-items: flex-start;
          gap: 6px;
        }
        .sc-val-icon { flex-shrink: 0; font-size: 14px; }
        .sc-val-error .sc-val-icon { color: var(--error-color, #f44336); }
        .sc-val-warning .sc-val-icon { color: var(--warning-color, #ff9800); }

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
        .sc-spinner-dark {
          border-color: rgba(0,0,0,0.15);
          border-top-color: var(--primary-color, #03a9f4);
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
        .sc-toggle-btn {
          background: none;
          border: none;
          color: var(--primary-color, #03a9f4);
          cursor: pointer;
          font-size: 12px;
          padding: 2px 6px;
          border-radius: 4px;
        }
        .sc-toggle-btn:hover { background: var(--primary-background-color, #f5f5f5); }
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
            <p>Write what you want in natural language. SmartChain will generate Home Assistant automation YAML using your real entities.</p>

            <div class="sc-row">
              <div>
                <label class="sc-label">Agent</label>
                <select id="agent-select-auto" class="sc-select">
                  <option value="">Auto (first available)</option>
                </select>
              </div>
            </div>

            <label class="sc-label">Target Entities (optional — narrows LLM context)</label>
            <div class="sc-entity-picker">
              <input type="text" id="entity-search" class="sc-entity-search"
                placeholder="Search entities... (e.g. light, kitchen, sensor)"
                autocomplete="off">
              <div id="entity-dropdown" class="sc-entity-dropdown"></div>
            </div>
            <div id="entity-chips" class="sc-chips"></div>

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
              <div class="sc-yaml-editor">
                <div class="sc-yaml-header">
                  <span id="yaml-info">YAML</span>
                  <div class="sc-yaml-header-actions">
                    <button id="btn-edit-toggle" class="sc-toggle-btn">Edit</button>
                  </div>
                </div>
                <div class="sc-yaml-body">
                  <div id="yaml-line-numbers" class="sc-line-numbers"></div>
                  <div id="yaml-display" class="sc-yaml-content"></div>
                  <textarea id="yaml-edit" class="sc-yaml-textarea sc-hidden"></textarea>
                </div>
              </div>

              <div id="validation-result" class="sc-hidden"></div>

              <div class="sc-btn-row">
                <button id="btn-validate" class="sc-btn sc-btn-warn">Validate</button>
                <button id="btn-deploy" class="sc-btn sc-btn-success">Deploy to HA</button>
                <button id="btn-regenerate" class="sc-btn sc-btn-outline">Regenerate</button>
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

            <div class="sc-row">
              <div>
                <label class="sc-label">Agent</label>
                <select id="agent-select-camera" class="sc-select">
                  <option value="">Auto (first available)</option>
                </select>
              </div>
              <div>
                <label class="sc-label">Camera</label>
                <select id="camera-select" class="sc-select">
                  <option value="">Select camera...</option>
                </select>
              </div>
            </div>

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
              <div class="sc-yaml-editor">
                <div class="sc-yaml-header"><span>Response</span></div>
                <div class="sc-yaml-body">
                  <pre id="camera-response" class="sc-yaml-content" style="white-space:pre-wrap;"></pre>
                </div>
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

    // Buttons
    this.querySelector("#btn-generate").addEventListener("click", () => this._handleGenerate());
    this.querySelector("#btn-regenerate").addEventListener("click", () => this._handleGenerate());
    this.querySelector("#btn-deploy").addEventListener("click", () => this._handleDeploy());
    this.querySelector("#btn-copy").addEventListener("click", () => this._handleCopy());
    this.querySelector("#btn-validate").addEventListener("click", () => this._handleValidate());
    this.querySelector("#btn-analyze").addEventListener("click", () => this._handleAnalyze());
    this.querySelector("#btn-edit-toggle").addEventListener("click", () => this._toggleEdit());

    // Entity picker
    this._setupEntityPicker();
  }

  // ── Entity Picker ──

  _setupEntityPicker() {
    const input = this.querySelector("#entity-search");
    const dropdown = this.querySelector("#entity-dropdown");

    input.addEventListener("focus", () => {
      this._renderEntityDropdown();
      dropdown.classList.add("open");
    });

    input.addEventListener("input", () => {
      this._entityFilter = input.value.toLowerCase();
      this._renderEntityDropdown();
      dropdown.classList.add("open");
    });

    document.addEventListener("click", (e) => {
      if (!this.querySelector(".sc-entity-picker")?.contains(e.target)) {
        dropdown.classList.remove("open");
      }
    });
  }

  _renderEntityDropdown() {
    const dropdown = this.querySelector("#entity-dropdown");
    if (!dropdown) return;

    const filter = this._entityFilter;
    const filtered = this._allEntities.filter((e) => {
      const text = `${e.id} ${e.name}`.toLowerCase();
      return !filter || text.includes(filter);
    });

    const limited = filtered.slice(0, 100);
    let html = "";
    let lastDomain = "";

    for (const entity of limited) {
      if (entity.domain !== lastDomain) {
        lastDomain = entity.domain;
        html += `<div class="sc-entity-domain">${entity.domain}</div>`;
      }
      const selected = this._selectedEntities.includes(entity.id) ? " selected" : "";
      const escapedId = entity.id.replace(/"/g, "&quot;");
      const escapedName = (entity.name || "").replace(/</g, "&lt;");
      html += `<div class="sc-entity-item${selected}" data-entity-id="${escapedId}">
        <span><span class="sc-entity-item-name">${escapedName}</span></span>
        <span class="sc-entity-item-id">${escapedId}</span>
      </div>`;
    }

    if (filtered.length > 100) {
      html += `<div class="sc-entity-domain">${filtered.length - 100} more...</div>`;
    }

    dropdown.innerHTML = html;

    dropdown.querySelectorAll(".sc-entity-item").forEach((item) => {
      item.addEventListener("click", () => {
        const eid = item.dataset.entityId;
        if (this._selectedEntities.includes(eid)) {
          this._selectedEntities = this._selectedEntities.filter((x) => x !== eid);
        } else {
          this._selectedEntities.push(eid);
        }
        this._renderEntityDropdown();
        this._renderChips();
      });
    });
  }

  _renderChips() {
    const container = this.querySelector("#entity-chips");
    if (!container) return;
    if (this._selectedEntities.length === 0) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = this._selectedEntities
      .map((eid) => {
        const escapedId = eid.replace(/"/g, "&quot;").replace(/</g, "&lt;");
        return `<span class="sc-chip">${escapedId}<span class="sc-chip-remove" data-entity-id="${eid}">&times;</span></span>`;
      })
      .join("");

    container.querySelectorAll(".sc-chip-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._selectedEntities = this._selectedEntities.filter((x) => x !== btn.dataset.entityId);
        this._renderChips();
        this._renderEntityDropdown();
      });
    });
  }

  // ── YAML Display ──

  _highlightYaml(yamlText) {
    const escaped = yamlText
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    return escaped.split("\n").map((line) => {
      // Comments
      if (line.trimStart().startsWith("#")) {
        return `<span class="sc-hl-comment">${line}</span>`;
      }
      // Key: value
      return line.replace(
        /^(\s*)([\w_.-]+)(:)(.*)/,
        (match, indent, key, colon, rest) => {
          let highlighted = rest;
          // entity_id highlighting
          highlighted = highlighted.replace(
            /\b([a-z_]+\.[a-z0-9_]+)\b/g,
            '<span class="sc-hl-entity">$1</span>'
          );
          // Quoted strings
          highlighted = highlighted.replace(
            /(["'])(.*?)\1/g,
            '<span class="sc-hl-string">$1$2$1</span>'
          );
          // Booleans
          highlighted = highlighted.replace(
            /\b(true|false|on|off)\b/gi,
            '<span class="sc-hl-bool">$1</span>'
          );
          // Numbers
          highlighted = highlighted.replace(
            /\b(\d+\.?\d*)\b/g,
            '<span class="sc-hl-number">$1</span>'
          );
          return `${indent}<span class="sc-hl-key">${key}</span>${colon}${highlighted}`;
        }
      );
    }).join("\n");
  }

  _updateYamlDisplay(yamlText) {
    this._generatedYaml = yamlText;
    const lines = yamlText.split("\n");

    // Line numbers
    const lineNumbers = this.querySelector("#yaml-line-numbers");
    if (lineNumbers) {
      lineNumbers.innerHTML = lines.map((_, i) => i + 1).join("\n");
    }

    // Highlighted display
    const display = this.querySelector("#yaml-display");
    if (display) {
      display.innerHTML = this._highlightYaml(yamlText);
    }

    // Info
    const info = this.querySelector("#yaml-info");
    if (info) {
      info.textContent = `YAML — ${lines.length} lines`;
    }

    // Edit textarea
    const edit = this.querySelector("#yaml-edit");
    if (edit) {
      edit.value = yamlText;
    }
  }

  _toggleEdit() {
    const display = this.querySelector("#yaml-display");
    const edit = this.querySelector("#yaml-edit");
    const btn = this.querySelector("#btn-edit-toggle");

    if (edit.classList.contains("sc-hidden")) {
      // Switch to edit mode
      edit.value = this._generatedYaml;
      edit.classList.remove("sc-hidden");
      display.classList.add("sc-hidden");
      btn.textContent = "Preview";
      edit.focus();
    } else {
      // Switch to preview mode — save edits
      this._generatedYaml = edit.value;
      this._updateYamlDisplay(this._generatedYaml);
      edit.classList.add("sc-hidden");
      display.classList.remove("sc-hidden");
      btn.textContent = "Edit";
      // Reset validation on edit
      this._validationResult = null;
      this.querySelector("#validation-result").classList.add("sc-hidden");
    }
  }

  // ── Handlers ──

  async _handleGenerate() {
    const desc = this.querySelector("#auto-description").value.trim();
    if (!desc) return;

    const btn = this.querySelector("#btn-generate");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Generating...';
    this.querySelector("#auto-result").classList.add("sc-hidden");
    this.querySelector("#auto-status").innerHTML = "";
    this.querySelector("#validation-result").classList.add("sc-hidden");
    this._deployed = false;
    this._validationResult = null;

    const agentId = this.querySelector("#agent-select-auto").value || undefined;

    try {
      const svcData = { description: desc };
      if (agentId) svcData.entity_id = agentId;
      if (this._selectedEntities.length > 0) svcData.entity_ids = this._selectedEntities;

      const resp = await this._callService("smartchain", "generate_automation", svcData);
      const data = resp.response?.["smartchain.generate_automation"] || resp.response || {};
      const yaml = data.automation_yaml || "";
      if (data.error) {
        this._showAutoStatus(data.error, true);
      } else if (yaml) {
        this._updateYamlDisplay(yaml);
        this.querySelector("#auto-result").classList.remove("sc-hidden");

        // Ensure we're in preview mode
        this.querySelector("#yaml-display").classList.remove("sc-hidden");
        this.querySelector("#yaml-edit").classList.add("sc-hidden");
        this.querySelector("#btn-edit-toggle").textContent = "Edit";

        // Reset deploy button
        const deployBtn = this.querySelector("#btn-deploy");
        deployBtn.disabled = false;
        deployBtn.textContent = "Deploy to HA";
      }
    } catch (err) {
      this._showAutoStatus("Error: " + (err.message || err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Generate";
    }
  }

  async _handleValidate() {
    if (!this._generatedYaml) return;

    // Sync from editor if in edit mode
    const edit = this.querySelector("#yaml-edit");
    if (!edit.classList.contains("sc-hidden")) {
      this._generatedYaml = edit.value;
    }

    const btn = this.querySelector("#btn-validate");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner" style="border-color:rgba(255,255,255,0.3);border-top-color:#fff;"></span>Validating...';

    try {
      const resp = await this._callService("smartchain", "validate_automation", {
        automation_yaml: this._generatedYaml,
      });
      const data = resp.response?.["smartchain.validate_automation"] || resp.response || {};
      this._validationResult = data;
      this._renderValidation(data);
    } catch (err) {
      this._renderValidation({
        valid: false,
        errors: ["Validation service error: " + (err.message || err)],
        warnings: [],
      });
    } finally {
      btn.disabled = false;
      btn.textContent = "Validate";
    }
  }

  _renderValidation(result) {
    const container = this.querySelector("#validation-result");
    if (!container) return;

    const errors = result.errors || [];
    const warnings = result.warnings || [];
    const valid = result.valid;

    let html = `<div class="sc-validation">
      <div class="sc-val-header ${valid ? "sc-val-valid" : "sc-val-invalid"}">
        ${valid ? "&#10003;" : "&#10007;"} ${valid ? "Valid" : "Invalid"} — ${errors.length} error(s), ${warnings.length} warning(s)
      </div>`;

    if (errors.length || warnings.length) {
      html += `<ul class="sc-val-list">`;
      for (const err of errors) {
        html += `<li class="sc-val-error"><span class="sc-val-icon">&#10007;</span> ${this._escapeHtml(err)}</li>`;
      }
      for (const warn of warnings) {
        html += `<li class="sc-val-warning"><span class="sc-val-icon">&#9888;</span> ${this._escapeHtml(warn)}</li>`;
      }
      html += `</ul>`;
    }

    html += `</div>`;
    container.innerHTML = html;
    container.classList.remove("sc-hidden");
  }

  _escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async _handleDeploy() {
    if (!this._generatedYaml || this._deployed) return;

    // Sync from editor if in edit mode
    const edit = this.querySelector("#yaml-edit");
    if (!edit.classList.contains("sc-hidden")) {
      this._generatedYaml = edit.value;
    }

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
        // Show validation details if available
        if (data.validation) {
          this._renderValidation(data.validation);
        }
        btn.disabled = false;
        btn.textContent = "Deploy to HA";
      }
    } catch (err) {
      this._showAutoStatus("Deploy failed: " + (err.message || err), true);
      btn.disabled = false;
      btn.textContent = "Deploy to HA";
    }
  }

  _handleCopy() {
    if (!this._generatedYaml) return;
    // Sync from editor if in edit mode
    const edit = this.querySelector("#yaml-edit");
    if (!edit.classList.contains("sc-hidden")) {
      this._generatedYaml = edit.value;
    }
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

    const agentId = this.querySelector("#agent-select-camera").value || undefined;

    const btn = this.querySelector("#btn-analyze");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Analyzing...';
    this.querySelector("#camera-result").classList.add("sc-hidden");

    try {
      const svcData = { camera_entity_id: camera, message: prompt };
      if (agentId) svcData.entity_id = agentId;

      const resp = await this._callService("smartchain", "analyze_image", svcData);
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
    el.innerHTML = `<div class="sc-status ${isError ? "sc-status-error" : "sc-status-success"}">${this._escapeHtml(message)}</div>`;
  }
}

customElements.define("smartchain-panel", SmartChainPanel);
