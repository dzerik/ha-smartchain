import { callService, extractResponse } from "../services.js";

const TYPE_LABELS = {
  automation: "Automations",
  script: "Scripts",
  scene: "Scenes",
  blueprint: "Blueprints",
};

const TYPE_ICONS = {
  automation: "\u2699\uFE0F",
  script: "\uD83D\uDCDC",
  scene: "\uD83C\uDFA8",
  blueprint: "\uD83D\uDCD0",
};

/**
 * <sc-yaml-picker> — Pick an existing automation/script/scene/blueprint and load its YAML.
 *
 * Properties:
 *   .hass = hass object
 *   .filterType = "automation" | null  — filter by type
 *
 * Events:
 *   "load" — fired when user selects an item, detail: { yaml, type, id, alias }
 */
export class ScYamlPicker extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._items = [];
    this._rendered = false;
    this._loading = false;
    this._filterType = null;
  }

  set hass(val) {
    this._hass = val;
  }

  set filterType(val) {
    this._filterType = val || null;
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
  }

  _render() {
    this.innerHTML = `
      <style>
        .yp-wrap {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          overflow: hidden;
          background: var(--card-background-color, #fff);
        }
        .yp-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: var(--primary-background-color, #fafafa);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 13px;
          font-weight: 500;
        }
        .yp-refresh {
          background: none; border: none;
          color: var(--primary-color, #03a9f4);
          cursor: pointer; font-size: 12px;
          padding: 2px 8px; border-radius: 4px;
        }
        .yp-refresh:hover { background: var(--divider-color, #e0e0e0); }
        .yp-search {
          width: 100%;
          padding: 8px 12px;
          border: none;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          font-size: 13px;
          outline: none;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          box-sizing: border-box;
        }
        .yp-list {
          max-height: 250px;
          overflow-y: auto;
        }
        .yp-group-label {
          padding: 6px 12px;
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
          color: var(--secondary-text-color, #888);
          background: var(--primary-background-color, #fafafa);
          position: sticky;
          top: 0;
        }
        .yp-item {
          display: flex;
          align-items: center;
          padding: 8px 12px;
          cursor: pointer;
          font-size: 13px;
          border-bottom: 1px solid var(--divider-color, #f0f0f0);
          color: var(--primary-text-color);
        }
        .yp-item:hover { background: var(--divider-color, #f5f5f5); }
        .yp-item-icon { margin-right: 8px; font-size: 14px; }
        .yp-item-alias { flex: 1; }
        .yp-item-id {
          font-size: 11px;
          color: var(--secondary-text-color, #999);
          margin-left: 8px;
          max-width: 120px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .yp-item-bp {
          font-size: 10px;
          color: var(--warning-color, #ff9800);
          margin-left: 6px;
          white-space: nowrap;
        }
        .yp-empty {
          padding: 16px 12px;
          text-align: center;
          color: var(--secondary-text-color, #999);
          font-size: 13px;
        }
        .yp-loading {
          padding: 16px 12px;
          text-align: center;
          color: var(--secondary-text-color, #999);
          font-size: 13px;
        }
      </style>
      <div class="yp-wrap">
        <div class="yp-header">
          <span>Existing YAML Items</span>
          <button class="yp-refresh" title="Refresh list">Refresh</button>
        </div>
        <input class="yp-search" type="text" placeholder="Search by name or id...">
        <div class="yp-list"></div>
      </div>
    `;

    this.querySelector(".yp-refresh").addEventListener("click", () => this._loadItems());
    this.querySelector(".yp-search").addEventListener("input", (e) => this._renderList(e.target.value));
  }

  async show() {
    if (!this._items.length) {
      await this._loadItems();
    }
    this._renderList("");
  }

  async _loadItems() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    const listEl = this.querySelector(".yp-list");
    listEl.innerHTML = '<div class="yp-loading">Loading...</div>';

    try {
      const svcData = {};
      if (this._filterType) svcData.type = this._filterType;
      const resp = await callService(this._hass, "smartchain", "list_yaml", svcData);
      const data = extractResponse(resp, "smartchain.list_yaml");
      this._items = data.items || [];
    } catch (err) {
      this._items = [];
      listEl.innerHTML = `<div class="yp-empty">Error: ${err.message || err}</div>`;
      this._loading = false;
      return;
    }

    this._loading = false;
    this._renderList(this.querySelector(".yp-search")?.value || "");
  }

  _renderList(query) {
    const listEl = this.querySelector(".yp-list");
    if (!listEl) return;

    const q = (query || "").toLowerCase();
    const filtered = this._items.filter(
      (item) =>
        !q ||
        (item.alias || "").toLowerCase().includes(q) ||
        (item.id || "").toLowerCase().includes(q)
    );

    if (!filtered.length) {
      listEl.innerHTML = '<div class="yp-empty">No items found</div>';
      return;
    }

    // Group by type
    const groups = {};
    for (const item of filtered) {
      const t = item.type || "other";
      if (!groups[t]) groups[t] = [];
      groups[t].push(item);
    }

    let html = "";
    for (const [type, items] of Object.entries(groups)) {
      html += `<div class="yp-group-label">${TYPE_ICONS[type] || ""} ${TYPE_LABELS[type] || type}</div>`;
      for (const item of items) {
        const alias = this._escapeHtml(item.alias || "Unnamed");
        const id = this._escapeHtml(item.id || "");
        const bpTag = item.blueprint_based
          ? '<span class="yp-item-bp" title="Blueprint-based. Direct edits break blueprint link.">blueprint</span>'
          : "";
        html += `<div class="yp-item" data-type="${type}" data-id="${this._escapeHtml(item.id)}" data-bp="${item.blueprint_based || false}">
          <span class="yp-item-icon">${TYPE_ICONS[type] || ""}</span>
          <span class="yp-item-alias">${alias}${bpTag}</span>
          <span class="yp-item-id">${id}</span>
        </div>`;
      }
    }

    listEl.innerHTML = html;

    // Click handlers
    listEl.querySelectorAll(".yp-item").forEach((el) => {
      el.addEventListener("click", () => this._selectItem(el.dataset.type, el.dataset.id));
    });
  }

  async _selectItem(type, id) {
    if (!this._hass) return;

    // Warn about blueprint-based automations
    const item = this._items.find((i) => i.type === type && i.id === id);
    if (item?.blueprint_based) {
      const ok = confirm(
        `"${item.alias}" is based on a blueprint.\n\n` +
        "Direct edits will break the blueprint link — " +
        "the automation will become standalone and won't receive blueprint updates.\n\n" +
        "Continue?"
      );
      if (!ok) return;
    }

    // Show loading state on clicked item
    const items = this.querySelectorAll(".yp-item");
    items.forEach((el) => {
      if (el.dataset.type === type && el.dataset.id === id) {
        el.style.opacity = "0.5";
      }
    });

    try {
      const resp = await callService(this._hass, "smartchain", "get_yaml", { type, id });
      const data = extractResponse(resp, "smartchain.get_yaml");

      if (data.error) {
        items.forEach((el) => (el.style.opacity = "1"));
        return;
      }

      const loadedItem = this._items.find((i) => i.type === type && i.id === id);
      this.dispatchEvent(
        new CustomEvent("load", {
          detail: {
            yaml: data.yaml || "",
            type: type,
            id: id,
            alias: loadedItem?.alias || "Unnamed",
          },
        })
      );
    } catch (err) {
      items.forEach((el) => (el.style.opacity = "1"));
    }
  }

  _escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

customElements.define("sc-yaml-picker", ScYamlPicker);
