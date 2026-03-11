import { callService, extractResponse, escapeHtml, getAgents, getAllEntities, populateSelect } from "../services.js";
import "./entity-picker.js";
import "./yaml-editor.js";
import "./validation-panel.js";

const TYPE_CONFIG = {
  automation: {
    label: "Automation",
    placeholder: "Turn on the coffee machine at 7:00 AM on weekdays if I'm home.",
    deployLabel: "Deploy to HA",
    yamlLabel: "Automation YAML",
  },
  script: {
    label: "Script",
    placeholder: "A script that turns off all lights, locks the door, and sets the thermostat to 18°C.",
    deployLabel: "Deploy Script",
    yamlLabel: "Script YAML",
  },
  scene: {
    label: "Scene",
    placeholder: "Movie night scene: dim living room lights to 20%, turn on TV, close blinds.",
    deployLabel: "Deploy Scene",
    yamlLabel: "Scene YAML",
  },
  blueprint: {
    label: "Blueprint",
    placeholder: "A blueprint that triggers a notification when a motion sensor detects movement, with configurable sensor, message and notification target.",
    deployLabel: "Save Blueprint",
    yamlLabel: "Blueprint YAML",
  },
};

/**
 * <sc-generate-tab> — generation tab supporting automation, script, scene, blueprint.
 *
 * Properties:
 *   .hass = hass object
 */
export class ScGenerateTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._deployed = false;
    this._generatedYaml = "";
    this._currentType = "automation";
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
    populateSelect(this.querySelector("#gt-agent"), agents, "Auto (first available)");
    const picker = this.querySelector("sc-entity-picker");
    if (picker) picker.entities = getAllEntities(this._hass);
  }

  _render() {
    this.innerHTML = `
      <div class="sc-card">
        <h2>Generate YAML</h2>
        <p>Select type, describe what you want, and SmartChain will generate valid YAML using your real entities.</p>

        <div class="sc-row">
          <div>
            <label class="sc-label">Type</label>
            <select id="gt-type" class="sc-select">
              <option value="automation">Automation</option>
              <option value="script">Script</option>
              <option value="scene">Scene</option>
              <option value="blueprint">Blueprint</option>
            </select>
          </div>
          <div>
            <label class="sc-label">Agent</label>
            <select id="gt-agent" class="sc-select">
              <option value="">Auto (first available)</option>
            </select>
          </div>
        </div>

        <label class="sc-label">Target Entities (optional)</label>
        <sc-entity-picker></sc-entity-picker>

        <label class="sc-label">Description</label>
        <textarea id="gt-description" class="sc-textarea"
          placeholder="${TYPE_CONFIG.automation.placeholder}"></textarea>
        <div class="sc-btn-row">
          <button id="gt-btn-generate" class="sc-btn sc-btn-primary">Generate</button>
        </div>
      </div>

      <div id="gt-result" class="sc-hidden">
        <div class="sc-card">
          <h2 id="gt-result-title">Generated Automation</h2>
          <sc-yaml-editor></sc-yaml-editor>
          <sc-validation-panel></sc-validation-panel>
          <div class="sc-btn-row">
            <button id="gt-btn-validate" class="sc-btn sc-btn-warn">Validate</button>
            <button id="gt-btn-deploy" class="sc-btn sc-btn-success">Deploy to HA</button>
            <button id="gt-btn-regenerate" class="sc-btn sc-btn-outline">Regenerate</button>
            <button id="gt-btn-copy" class="sc-btn sc-btn-outline">Copy YAML</button>
          </div>
          <div id="gt-status"></div>
        </div>
      </div>
    `;

    // Type change → update placeholder and labels
    this.querySelector("#gt-type").addEventListener("change", (e) => {
      this._currentType = e.target.value;
      const cfg = TYPE_CONFIG[this._currentType];
      this.querySelector("#gt-description").placeholder = cfg.placeholder;
      this.querySelector("#gt-btn-deploy").textContent = cfg.deployLabel;
      this.querySelector("#gt-result-title").textContent = `Generated ${cfg.label}`;
      const editor = this.querySelector("sc-yaml-editor");
      if (editor) editor.label = cfg.yamlLabel;
    });

    // Buttons
    this.querySelector("#gt-btn-generate").addEventListener("click", () => this._handleGenerate());
    this.querySelector("#gt-btn-regenerate").addEventListener("click", () => this._handleGenerate());
    this.querySelector("#gt-btn-deploy").addEventListener("click", () => this._handleDeploy());
    this.querySelector("#gt-btn-copy").addEventListener("click", () => this._handleCopy());
    this.querySelector("#gt-btn-validate").addEventListener("click", () => this._handleValidate());
  }

  async _handleGenerate() {
    const desc = this.querySelector("#gt-description").value.trim();
    if (!desc) return;

    const btn = this.querySelector("#gt-btn-generate");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Generating...';
    this.querySelector("#gt-result").classList.add("sc-hidden");
    this.querySelector("#gt-status").innerHTML = "";
    this.querySelector("sc-validation-panel").clear();
    this._deployed = false;

    const agentId = this.querySelector("#gt-agent").value || undefined;
    const picker = this.querySelector("sc-entity-picker");
    const entityIds = picker?.selected?.length ? picker.selected : undefined;

    try {
      const svcData = {
        description: desc,
        type: this._currentType,
      };
      if (agentId) svcData.entity_id = agentId;
      if (entityIds) svcData.entity_ids = entityIds;

      const resp = await callService(this._hass, "smartchain", "generate_automation", svcData);
      const data = extractResponse(resp, "smartchain.generate_automation");
      const yaml = data.automation_yaml || "";

      if (data.error) {
        this._showStatus(data.error, true);
      } else if (yaml) {
        this._generatedYaml = yaml;
        const editor = this.querySelector("sc-yaml-editor");
        const cfg = TYPE_CONFIG[this._currentType];
        editor.label = cfg.yamlLabel;
        editor.value = yaml;
        this.querySelector("#gt-result-title").textContent = `Generated ${cfg.label}`;
        this.querySelector("#gt-result").classList.remove("sc-hidden");

        // Reset deploy button
        const deployBtn = this.querySelector("#gt-btn-deploy");
        deployBtn.disabled = false;
        deployBtn.textContent = cfg.deployLabel;
      }
    } catch (err) {
      this._showStatus("Error: " + (err.message || err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Generate";
    }
  }

  async _handleValidate() {
    const editor = this.querySelector("sc-yaml-editor");
    const yaml = editor?.value;
    if (!yaml) return;

    const btn = this.querySelector("#gt-btn-validate");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner" style="border-color:rgba(255,255,255,0.3);border-top-color:#fff;"></span>Validating...';

    try {
      const resp = await callService(this._hass, "smartchain", "validate_automation", {
        automation_yaml: yaml,
      });
      const data = extractResponse(resp, "smartchain.validate_automation");
      this.querySelector("sc-validation-panel").result = data;
    } catch (err) {
      this.querySelector("sc-validation-panel").result = {
        valid: false,
        errors: ["Validation error: " + (err.message || err)],
        warnings: [],
      };
    } finally {
      btn.disabled = false;
      btn.textContent = "Validate";
    }
  }

  async _handleDeploy() {
    const editor = this.querySelector("sc-yaml-editor");
    const yaml = editor?.value;
    if (!yaml || this._deployed) return;

    const btn = this.querySelector("#gt-btn-deploy");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>Deploying...';

    try {
      const resp = await callService(this._hass, "smartchain", "deploy_automation", {
        automation_yaml: yaml,
        type: this._currentType,
      });
      const data = extractResponse(resp, "smartchain.deploy_automation");
      if (data.deployed) {
        this._deployed = true;
        this._showStatus(
          `${TYPE_CONFIG[this._currentType].label} "${data.alias || "Unnamed"}" deployed!`,
          false
        );
        btn.textContent = "Deployed!";
      } else if (data.error) {
        this._showStatus(data.error, true);
        if (data.validation) {
          this.querySelector("sc-validation-panel").result = data.validation;
        }
        btn.disabled = false;
        btn.textContent = TYPE_CONFIG[this._currentType].deployLabel;
      }
    } catch (err) {
      this._showStatus("Deploy failed: " + (err.message || err), true);
      btn.disabled = false;
      btn.textContent = TYPE_CONFIG[this._currentType].deployLabel;
    }
  }

  _handleCopy() {
    const editor = this.querySelector("sc-yaml-editor");
    const yaml = editor?.value;
    if (!yaml) return;
    navigator.clipboard.writeText(yaml).then(() => {
      const btn = this.querySelector("#gt-btn-copy");
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy YAML"), 2000);
    });
  }

  _showStatus(message, isError) {
    const el = this.querySelector("#gt-status");
    if (el) el.innerHTML = `<div class="sc-status ${isError ? "sc-status-error" : "sc-status-success"}">${escapeHtml(message)}</div>`;
  }
}

customElements.define("sc-generate-tab", ScGenerateTab);
