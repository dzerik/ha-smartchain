import { callService, extractResponse, escapeHtml, showConfirm } from "../services.js";

const TYPE_META = {
  automation: { icon: "mdi:cog-transfer", label: "Automations" },
  script:     { icon: "mdi:script-text",   label: "Scripts" },
  scene:      { icon: "mdi:palette",       label: "Scenes" },
  blueprint:  { icon: "mdi:floor-plan",    label: "Blueprints" },
};

/**
 * <sc-sidebar-explorer> — file-explorer style sidebar for HA YAML items.
 *
 * Events: "select" { yaml, type, id, alias }, "new"
 */
export class ScSidebarExplorer extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._items = [];
    this._activeType = null;
    this._activeId = null;
    this._query = "";
    this._loading = false;
    this._rendered = false;
  }

  set hass(val) { this._hass = val; }

  connectedCallback() {
    if (!this._rendered) {
      this.style.cssText = "display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden;";
      this._render();
      this._rendered = true;
      this._loadItems();
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .se-types {
          display: flex;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
        }
        .se-type-btn {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 10px 4px;
          border: none;
          background: none;
          cursor: pointer;
          color: var(--secondary-text-color, #888);
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
        }
        .se-type-btn:hover { color: var(--primary-text-color); background: var(--divider-color, #f5f5f5); }
        .se-type-btn.active {
          color: var(--primary-color, #03a9f4);
          border-bottom-color: var(--primary-color, #03a9f4);
        }
        .se-type-btn ha-icon { --mdc-icon-size: 18px; }
        .se-search-wrap { padding: 10px 12px; border-bottom: 1px solid var(--divider-color, #e0e0e0); flex-shrink: 0; }
        .se-search {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 13px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          box-sizing: border-box;
          transition: border-color 0.2s;
        }
        .se-search:focus { outline: none; border-color: var(--primary-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 15%, transparent); }
        .se-list { flex: 1; overflow-y: auto; overflow-x: hidden; }
        .se-group {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 14px 6px;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--secondary-text-color, #888);
          position: sticky;
          top: 0;
          background: var(--card-background-color, #fff);
          z-index: 1;
        }
        .se-group ha-icon { --mdc-icon-size: 14px; }
        .se-group-count {
          font-weight: 400;
          font-size: 10px;
          color: var(--disabled-text-color, #aaa);
        }
        .se-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 14px;
          cursor: pointer;
          font-size: 13px;
          color: var(--primary-text-color);
          border-left: 3px solid transparent;
          transition: all 0.15s;
        }
        .se-item:hover { background: var(--primary-background-color, #f5f5f5); }
        .se-item.active {
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent);
          border-left-color: var(--primary-color, #03a9f4);
        }
        .se-item ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); flex-shrink: 0; }
        .se-item.active ha-icon { color: var(--primary-color); }
        .se-item-name {
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .se-item-badge {
          font-size: 10px;
          padding: 2px 7px;
          border-radius: 10px;
          background: color-mix(in srgb, var(--warning-color, #ff9800) 20%, transparent);
          color: var(--warning-color, #ff9800);
          font-weight: 600;
          flex-shrink: 0;
        }
        .se-empty {
          padding: 32px 16px;
          text-align: center;
          color: var(--secondary-text-color);
          font-size: 13px;
        }
        .se-empty ha-icon { --mdc-icon-size: 40px; display: block; margin: 0 auto 12px; opacity: 0.3; }
        .se-footer {
          padding: 10px 12px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
          display: flex;
          gap: 8px;
        }
        .se-footer .sc-btn { flex: 1; text-align: center; }
      </style>

      <div class="se-types">
        <button class="se-type-btn active" data-type="" title="All types">
          <ha-icon icon="mdi:view-grid"></ha-icon>
        </button>
        ${Object.entries(TYPE_META).map(([type, m]) =>
          `<button class="se-type-btn" data-type="${type}" title="${m.label}"><ha-icon icon="${m.icon}"></ha-icon></button>`
        ).join("")}
      </div>
      <div class="se-search-wrap">
        <input class="se-search" type="text" placeholder="Search..." autocomplete="off">
      </div>
      <div class="se-list"></div>
      <div class="se-footer">
        <button class="sc-btn sc-btn-primary se-new-btn">
          <ha-icon icon="mdi:plus"></ha-icon> New
        </button>
        <button class="sc-btn sc-btn-ghost se-refresh-btn">
          <ha-icon icon="mdi:refresh"></ha-icon>
        </button>
      </div>
    `;

    this.querySelectorAll(".se-type-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.querySelectorAll(".se-type-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this._activeType = btn.dataset.type || null;
        this._renderList();
      });
    });

    this.querySelector(".se-search").addEventListener("input", (e) => {
      this._query = e.target.value.toLowerCase();
      this._renderList();
    });

    this.querySelector(".se-new-btn").addEventListener("click", () => {
      this._activeId = null;
      this._renderList();
      this.dispatchEvent(new CustomEvent("new"));
    });

    this.querySelector(".se-refresh-btn").addEventListener("click", () => this._loadItems());
  }

  async _loadItems() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    const listEl = this.querySelector(".se-list");
    if (listEl) listEl.innerHTML = '<div class="se-empty"><ha-icon icon="mdi:loading"></ha-icon>Loading...</div>';

    try {
      const resp = await callService(this._hass, "smartchain", "list_yaml", {});
      const data = extractResponse(resp, "smartchain.list_yaml");
      this._items = data.items || [];
    } catch {
      this._items = [];
    }

    this._loading = false;
    this._renderList();
  }

  _renderList() {
    const listEl = this.querySelector(".se-list");
    if (!listEl) return;

    const q = this._query;
    const typeFilter = this._activeType;
    const filtered = this._items.filter((item) => {
      if (typeFilter && item.type !== typeFilter) return false;
      if (q) {
        const text = `${item.alias || ""} ${item.id || ""}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });

    if (!filtered.length) {
      listEl.innerHTML = '<div class="se-empty"><ha-icon icon="mdi:file-document-outline"></ha-icon>No items found</div>';
      return;
    }

    const groups = {};
    for (const item of filtered) {
      const t = item.type || "other";
      if (!groups[t]) groups[t] = [];
      groups[t].push(item);
    }

    let html = "";
    for (const [type, items] of Object.entries(groups)) {
      const meta = TYPE_META[type] || { icon: "mdi:file", label: type };
      html += `<div class="se-group">
        <ha-icon icon="${meta.icon}"></ha-icon>
        ${meta.label}
        <span class="se-group-count">${items.length}</span>
      </div>`;
      for (const item of items) {
        const alias = escapeHtml(item.alias || "Unnamed");
        const isActive = this._activeId === `${item.type}:${item.id}`;
        const badge = item.blueprint_based ? '<span class="se-item-badge">BP</span>' : "";
        html += `<div class="se-item${isActive ? " active" : ""}" data-type="${escapeHtml(item.type)}" data-id="${escapeHtml(item.id)}">
          <ha-icon icon="${meta.icon}"></ha-icon>
          <span class="se-item-name">${alias}</span>
          ${badge}
        </div>`;
      }
    }

    listEl.innerHTML = html;
    listEl.querySelectorAll(".se-item").forEach((el) => {
      el.addEventListener("click", () => this._selectItem(el.dataset.type, el.dataset.id));
    });
  }

  async _selectItem(type, id) {
    if (!this._hass) return;

    const item = this._items.find((i) => i.type === type && i.id === id);
    if (item?.blueprint_based) {
      const ok = await showConfirm(
        "Blueprint-based item",
        `"${item.alias}" is based on a blueprint. Direct edits will break the blueprint link and the item won't receive blueprint updates.`,
        "Edit anyway",
        "sc-btn-warn"
      );
      if (!ok) return;
    }

    this._activeId = `${type}:${id}`;
    this._renderList();

    try {
      const resp = await callService(this._hass, "smartchain", "get_yaml", { type, id });
      const data = extractResponse(resp, "smartchain.get_yaml");
      if (data.error) return;

      this.dispatchEvent(new CustomEvent("select", {
        detail: { yaml: data.yaml || "", type, id, alias: item?.alias || "Unnamed" },
      }));
    } catch { /* ignore */ }
  }

  setActive(type, id) {
    this._activeId = type && id ? `${type}:${id}` : null;
    this._renderList();
  }
}

customElements.define("sc-sidebar-explorer", ScSidebarExplorer);
