import { callService, extractResponse, getAgents, getAllEntities, populateSelect } from "../services.js";
import "./entity-picker.js";

/**
 * <sc-ai-bar> — AI assistant bar for describing changes to LLM.
 *
 * Properties:
 *   .hass
 *   .currentYaml — current editor content (to send as source_yaml)
 *   .currentType — "automation" | "script" | "scene" | "blueprint"
 *
 * Events:
 *   "result" — { yaml, isNew } — LLM returned YAML
 *   "error"  — { message }
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
          gap: 8px;
          padding: 8px 12px;
        }
        .ab-input-wrap { flex: 1; }
        .ab-input {
          width: 100%;
          padding: 8px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 13px;
          font-family: inherit;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          resize: none;
          min-height: 36px;
          max-height: 120px;
          box-sizing: border-box;
        }
        .ab-input:focus { outline: none; border-color: var(--primary-color); }
        .ab-actions { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
        .ab-options {
          display: none;
          padding: 6px 12px 10px;
          border-top: 1px solid var(--divider-color, #eee);
          gap: 10px;
        }
        .ab-options.open { display: flex; flex-wrap: wrap; align-items: flex-end; }
        .ab-opt-group { display: flex; flex-direction: column; gap: 2px; }
        .ab-opt-group label { font-size: 10px; font-weight: 600; text-transform: uppercase; color: var(--secondary-text-color); }
        .ab-opt-group select {
          padding: 4px 8px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          font-size: 12px;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
        }
        .ab-entity-wrap { display: none; padding: 0 12px 8px; }
        .ab-entity-wrap.open { display: block; }
        .ab-status {
          padding: 4px 12px;
          font-size: 12px;
        }
        .ab-status-err { color: var(--error-color, #f44336); }
        .ab-status-ok { color: var(--success-color, #4caf50); }
      </style>
      <div class="ab-wrap">
        <div class="ab-main">
          <div class="ab-input-wrap">
            <textarea class="ab-input" rows="1"
              placeholder="Describe what to generate or change..."></textarea>
          </div>
          <div class="ab-actions">
            <button class="sc-btn sc-btn-icon ab-toggle-opts" title="Options">\u2699</button>
            <button class="sc-btn sc-btn-icon ab-toggle-entities" title="Entity picker">\uD83C\uDFAF</button>
            <button class="sc-btn sc-btn-primary ab-apply">Apply</button>
          </div>
        </div>
        <div class="ab-options">
          <div class="ab-opt-group">
            <label>Agent</label>
            <select class="ab-agent"></select>
          </div>
          <div class="ab-opt-group">
            <label>Type</label>
            <select class="ab-type">
              <option value="automation">Automation</option>
              <option value="script">Script</option>
              <option value="scene">Scene</option>
              <option value="blueprint">Blueprint</option>
            </select>
          </div>
        </div>
        <div class="ab-entity-wrap">
          <sc-entity-picker></sc-entity-picker>
        </div>
        <div class="ab-status"></div>
      </div>
    `;

    // Auto-resize textarea
    const input = this.querySelector(".ab-input");
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

    // Enter to submit (Shift+Enter for newline)
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._handleApply();
      }
    });

    // Toggle options
    this.querySelector(".ab-toggle-opts").addEventListener("click", () => {
      this.querySelector(".ab-options").classList.toggle("open");
    });

    // Toggle entity picker
    this.querySelector(".ab-toggle-entities").addEventListener("click", () => {
      this._entityPickerOpen = !this._entityPickerOpen;
      this.querySelector(".ab-entity-wrap").classList.toggle("open", this._entityPickerOpen);
    });

    // Type sync
    this.querySelector(".ab-type").addEventListener("change", (e) => {
      this._currentType = e.target.value;
    });

    // Apply button
    this.querySelector(".ab-apply").addEventListener("click", () => this._handleApply());
  }

  async _handleApply() {
    const desc = this.querySelector(".ab-input").value.trim();
    if (!desc || this._loading) return;

    this._loading = true;
    const btn = this.querySelector(".ab-apply");
    btn.disabled = true;
    btn.innerHTML = '<span class="sc-spinner"></span>';
    this._setStatus("");

    const agentId = this.querySelector(".ab-agent")?.value || undefined;
    const picker = this.querySelector("sc-entity-picker");
    const entityIds = picker?.selected?.length ? picker.selected : undefined;
    const hasSource = this._currentYaml.trim().length > 0;

    try {
      const svcData = {
        description: desc,
        type: this._currentType,
      };
      if (agentId) svcData.entity_id = agentId;
      if (entityIds) svcData.entity_ids = entityIds;
      if (hasSource) svcData.source_yaml = this._currentYaml;

      const resp = await callService(this._hass, "smartchain", "generate_automation", svcData);
      const data = extractResponse(resp, "smartchain.generate_automation");
      let yaml = data.automation_yaml || "";

      if (data.error) {
        this._setStatus(data.error, true);
        this.dispatchEvent(new CustomEvent("error", { detail: { message: data.error } }));
      } else if (yaml) {
        // Strip code fences
        if (yaml.startsWith("```")) {
          const lines = yaml.split("\n").filter((l) => !l.startsWith("```"));
          yaml = lines.join("\n").trim();
        }
        this.dispatchEvent(new CustomEvent("result", { detail: { yaml, isNew: !hasSource } }));
        this._setStatus("Done", false);
        // Clear input
        const input = this.querySelector(".ab-input");
        input.value = "";
        input.style.height = "auto";
      }
    } catch (err) {
      this._setStatus("Error: " + (err.message || err), true);
      this.dispatchEvent(new CustomEvent("error", { detail: { message: String(err) } }));
    } finally {
      this._loading = false;
      btn.disabled = false;
      btn.textContent = "Apply";
    }
  }

  _setStatus(msg, isError) {
    const el = this.querySelector(".ab-status");
    if (!el) return;
    if (!msg) { el.innerHTML = ""; return; }
    el.innerHTML = `<span class="${isError ? "ab-status-err" : "ab-status-ok"}">${msg}</span>`;
    if (!isError) setTimeout(() => { if (el) el.innerHTML = ""; }, 3000);
  }

  /** Update type selector from outside */
  setType(type) {
    this._currentType = type;
    const sel = this.querySelector(".ab-type");
    if (sel) sel.value = type;
  }
}

customElements.define("sc-ai-bar", ScAiBar);
