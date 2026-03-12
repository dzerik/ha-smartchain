import { callService, extractResponse, getAgents, getAllEntities, populateSelect, showToast } from "../services.js";
import "./entity-picker.js";

/**
 * <sc-ai-bar> — AI prompt bar for describing changes to LLM.
 *
 * Properties: .hass, .currentYaml, .currentType
 * Events: "result" { yaml, isNew }, "error" { message }
 */
export class ScAiBar extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._currentYaml = "";
    this._currentType = "automation";
    this._rendered = false;
    this._loading = false;
  }

  set hass(val) {
    this._hass = val;
    if (this._rendered) this._refreshSelectors();
  }
  set currentYaml(val) { this._currentYaml = val || ""; }
  set currentType(val) { this._currentType = val || "automation"; }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass) this._refreshSelectors();
  }

  _refreshSelectors() {
    const agents = getAgents(this._hass);
    populateSelect(this.querySelector(".ab-agent"), agents, "Auto");
  }

  _render() {
    this.innerHTML = `
      <style>
        .ab-wrap {
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--card-background-color, #fff);
          flex-shrink: 0;
          padding: 10px 16px;
        }
        .ab-row {
          display: flex;
          gap: 10px;
          align-items: flex-end;
        }
        .ab-prompt-wrap {
          flex: 1;
          min-width: 0;
          position: relative;
        }
        .ab-prompt-label {
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--secondary-text-color, #888);
          margin-bottom: 4px;
        }
        .ab-input {
          width: 100%;
          padding: 10px 14px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 10px;
          font-size: 14px;
          font-family: inherit;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          resize: none;
          box-sizing: border-box;
          transition: border-color 0.2s, box-shadow 0.2s;
          line-height: 1.5;
        }
        .ab-input:focus {
          outline: none;
          border-color: var(--primary-color);
          box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 15%, transparent);
        }
        .ab-input::placeholder { color: var(--secondary-text-color, #999); }
        .ab-side {
          display: flex;
          flex-direction: column;
          gap: 6px;
          flex-shrink: 0;
        }
        .ab-selectors {
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .ab-select {
          padding: 6px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 13px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          max-width: 140px;
        }
        .ab-btn-row {
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .ab-apply {
          padding: 8px 20px;
          border: none;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: #fff;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: opacity 0.2s;
          white-space: nowrap;
        }
        .ab-apply:hover { opacity: 0.9; }
        .ab-apply:disabled { opacity: 0.5; cursor: not-allowed; }
        .ab-apply ha-icon { --mdc-icon-size: 18px; }
        .ab-entity-btn {
          padding: 6px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: none;
          cursor: pointer;
          color: var(--secondary-text-color, #888);
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
          transition: all 0.2s;
        }
        .ab-entity-btn:hover { border-color: var(--primary-color); color: var(--primary-text-color); }
        .ab-entity-btn.active { border-color: var(--primary-color); color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
        .ab-entity-btn ha-icon { --mdc-icon-size: 16px; }
        .ab-entity-count {
          background: var(--primary-color, #03a9f4);
          color: #fff;
          border-radius: 10px;
          padding: 0 6px;
          font-size: 11px;
          font-weight: 600;
          min-width: 16px;
          text-align: center;
          display: none;
        }

        /* Entity modal */
        .ab-modal-overlay {
          display: none;
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.5);
          z-index: 9999;
          align-items: center;
          justify-content: center;
        }
        .ab-modal-overlay.open { display: flex; }
        .ab-modal {
          background: var(--card-background-color, #1e1e1e);
          border-radius: 16px;
          width: 90%;
          max-width: 500px;
          max-height: 70vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        }
        .ab-modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px 12px;
          border-bottom: 1px solid var(--divider-color, #444);
        }
        .ab-modal-header h3 { margin: 0; font-size: 16px; font-weight: 600; color: var(--primary-text-color, #fff); }
        .ab-modal-close {
          background: none;
          border: none;
          cursor: pointer;
          color: var(--secondary-text-color, #888);
          padding: 4px;
        }
        .ab-modal-close ha-icon { --mdc-icon-size: 20px; }
        .ab-modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 12px 20px 20px;
        }
      </style>

      <div class="ab-wrap">
        <div class="ab-row">
          <div class="ab-prompt-wrap">
            <div class="ab-prompt-label">AI Prompt</div>
            <textarea class="ab-input" rows="3"
              placeholder="Describe what to generate or change...\nExample: Turn on lights when motion detected in hallway"></textarea>
          </div>
          <div class="ab-side">
            <div class="ab-selectors">
              <select class="ab-agent ab-select" title="AI Agent"></select>
              <select class="ab-type ab-select" title="YAML type">
                <option value="automation">Automation</option>
                <option value="script">Script</option>
                <option value="scene">Scene</option>
                <option value="blueprint">Blueprint</option>
              </select>
            </div>
            <div class="ab-btn-row">
              <button class="ab-entity-btn" title="Select entities for context">
                <ha-icon icon="mdi:crosshairs-gps"></ha-icon>
                Entities
                <span class="ab-entity-count">0</span>
              </button>
              <button class="ab-apply" title="Send to AI (Ctrl+Enter)">
                <ha-icon icon="mdi:auto-fix"></ha-icon> Apply
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="ab-modal-overlay">
        <div class="ab-modal">
          <div class="ab-modal-header">
            <h3>Select Entities</h3>
            <button class="ab-modal-close"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>
          <div class="ab-modal-body">
            <sc-entity-picker inline></sc-entity-picker>
          </div>
        </div>
      </div>
    `;

    // Auto-resize textarea
    const input = this.querySelector(".ab-input");
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 160) + "px";
    });

    // Ctrl+Enter to submit
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this._handleApply();
      }
    });

    // Entity modal
    const modalOverlay = this.querySelector(".ab-modal-overlay");
    const entityBtn = this.querySelector(".ab-entity-btn");

    entityBtn.addEventListener("click", () => {
      modalOverlay.classList.add("open");
      // Refresh entities when opening
      const picker = this.querySelector("sc-entity-picker");
      if (picker && this._hass) picker.entities = getAllEntities(this._hass);
    });

    this.querySelector(".ab-modal-close").addEventListener("click", () => {
      modalOverlay.classList.remove("open");
      this._updateEntityCount();
    });

    modalOverlay.addEventListener("click", (e) => {
      if (e.target === modalOverlay) {
        modalOverlay.classList.remove("open");
        this._updateEntityCount();
      }
    });

    // Type sync
    this.querySelector(".ab-type").addEventListener("change", (e) => {
      this._currentType = e.target.value;
    });

    // Apply
    this.querySelector(".ab-apply").addEventListener("click", () => this._handleApply());
  }

  _updateEntityCount() {
    const picker = this.querySelector("sc-entity-picker");
    const count = picker?.selected?.length || 0;
    const badge = this.querySelector(".ab-entity-count");
    const btn = this.querySelector(".ab-entity-btn");
    if (badge) {
      badge.textContent = count;
      badge.style.display = count > 0 ? "" : "none";
    }
    if (btn) btn.classList.toggle("active", count > 0);
  }

  async _handleApply() {
    const desc = this.querySelector(".ab-input").value.trim();
    if (!desc || this._loading) return;

    this._loading = true;
    const btn = this.querySelector(".ab-apply");
    btn.disabled = true;
    const icon = btn.querySelector("ha-icon");
    icon.icon = "mdi:loading";
    const textNode = icon.nextSibling;
    if (textNode) textNode.textContent = "";

    const agentId = this.querySelector(".ab-agent")?.value || undefined;
    const picker = this.querySelector("sc-entity-picker");
    const entityIds = picker?.selected?.length ? picker.selected : undefined;
    const hasSource = this._currentYaml.trim().length > 0;

    try {
      const svcData = { description: desc, type: this._currentType };
      if (agentId) svcData.entity_id = agentId;
      if (entityIds) svcData.entity_ids = entityIds;
      if (hasSource) svcData.source_yaml = this._currentYaml;

      const resp = await callService(this._hass, "smartchain", "generate_automation", svcData);
      const data = extractResponse(resp, "smartchain.generate_automation");
      let yaml = data.automation_yaml || "";

      if (data.error) {
        showToast(data.error, "error", 5000);
        this.dispatchEvent(new CustomEvent("error", { detail: { message: data.error } }));
      } else if (yaml) {
        if (yaml.startsWith("```")) {
          yaml = yaml.split("\n").filter((l) => !l.startsWith("```")).join("\n").trim();
        }
        this.dispatchEvent(new CustomEvent("result", { detail: { yaml, isNew: !hasSource } }));
        showToast("AI changes applied", "success");
        const input = this.querySelector(".ab-input");
        input.value = "";
        input.style.height = "auto";
      }
    } catch (err) {
      showToast("Error: " + (err.message || err), "error", 5000);
      this.dispatchEvent(new CustomEvent("error", { detail: { message: String(err) } }));
    } finally {
      this._loading = false;
      btn.disabled = false;
      icon.icon = "mdi:auto-fix";
      if (textNode) textNode.textContent = " Apply";
    }
  }

  setType(type) {
    this._currentType = type;
    const sel = this.querySelector(".ab-type");
    if (sel) sel.value = type;
  }
}

customElements.define("sc-ai-bar", ScAiBar);
