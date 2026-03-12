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
    this._entityPickerOpen = false;
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
    const picker = this.querySelector("sc-entity-picker");
    if (picker) picker.entities = getAllEntities(this._hass);
  }

  _render() {
    this.innerHTML = `
      <style>
        .ab-wrap {
          border-top: 1px solid var(--divider-color, #e0e0e0);
          background: var(--card-background-color, #fff);
          flex-shrink: 0;
        }
        .ab-main {
          display: flex;
          align-items: flex-end;
          gap: 10px;
          padding: 10px 16px;
        }
        .ab-input-wrap {
          flex: 1;
          position: relative;
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
          min-height: 40px;
          max-height: 120px;
          box-sizing: border-box;
          transition: border-color 0.2s, box-shadow 0.2s;
        }
        .ab-input:focus { outline: none; border-color: var(--primary-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 15%, transparent); }
        .ab-actions { display: flex; gap: 8px; flex-shrink: 0; align-items: center; }
        .ab-inline-select {
          padding: 6px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 13px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          max-width: 160px;
        }
        .ab-entity-wrap {
          display: none;
          padding: 0 16px 10px;
        }
        .ab-entity-wrap.open { display: block; }
      </style>

      <div class="ab-wrap">
        <div class="ab-main">
          <div class="ab-input-wrap">
            <textarea class="ab-input" rows="1"
              placeholder="Describe what to generate or change..."></textarea>
          </div>
          <div class="ab-actions">
            <select class="ab-agent ab-inline-select" title="Select agent"></select>
            <select class="ab-type ab-inline-select" title="YAML type">
              <option value="automation">Automation</option>
              <option value="script">Script</option>
              <option value="scene">Scene</option>
              <option value="blueprint">Blueprint</option>
            </select>
            <button class="sc-btn sc-btn-icon ab-toggle-entities" title="Entity picker">
              <ha-icon icon="mdi:crosshairs-gps"></ha-icon>
            </button>
            <button class="sc-btn sc-btn-primary ab-apply">
              <ha-icon icon="mdi:auto-fix"></ha-icon> Apply
            </button>
          </div>
        </div>
        <div class="ab-entity-wrap">
          <sc-entity-picker></sc-entity-picker>
        </div>
      </div>
    `;

    // Auto-resize textarea
    const input = this.querySelector(".ab-input");
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

    // Enter to submit
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._handleApply();
      }
    });

    // Toggle entity picker
    this.querySelector(".ab-toggle-entities").addEventListener("click", () => {
      this._entityPickerOpen = !this._entityPickerOpen;
      this.querySelector(".ab-entity-wrap").classList.toggle("open", this._entityPickerOpen);
      const btn = this.querySelector(".ab-toggle-entities");
      btn.classList.toggle("active", this._entityPickerOpen);
    });

    // Type sync
    this.querySelector(".ab-type").addEventListener("change", (e) => {
      this._currentType = e.target.value;
    });

    // Apply
    this.querySelector(".ab-apply").addEventListener("click", () => this._handleApply());
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
        // Strip code fences
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
