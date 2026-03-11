import { callService, extractResponse, escapeHtml } from "../services.js";

const TYPE_ICONS = {
  automation: "\u2699\uFE0F",
  script: "\uD83D\uDCDC",
  scene: "\uD83C\uDFA8",
  blueprint: "\uD83D\uDCD0",
};

const TYPE_LABELS = {
  automation: "Automations",
  script: "Scripts",
  scene: "Scenes",
  blueprint: "Blueprints",
};

/**
 * <sc-sidebar-explorer> — file-explorer style sidebar for HA YAML items.
 *
 * Properties:
 *   .hass
 *
 * Events:
 *   "select" — { yaml, type, id, alias }
 *   "new"    — user wants to create a new item
 */
export class ScSidebarExplorer extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._items = [];
    this._activeType = null; // null = all
    this._activeId = null;
    this._query = "";
    this._loading = false;
    this._rendered = false;
  }

  set hass(val) {
    this._hass = val;
  }

  connectedCallback() {
    if (!this._rendered) {
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
          gap: 0;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
        }
        .se-type-btn {
          flex: 1;
          padding: 8px 4px;
          border: none;
          background: none;
          font-size: 11px;
          cursor: pointer;
          color: var(--secondary-text-color, #888);
          border-bottom: 2px solid transparent;
          transition: all 0.15s;
          text-align: center;
        }
        .se-type-btn:hover { color: var(--primary-text-color); }
        .se-type-btn.active {
          color: var(--primary-color, #03a9f4);
          border-bottom-color: var(--primary-color, #03a9f4);
        }
        .se-search-wrap {
          padding: 8px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
        }
        .se-search {
          width: 100%;
          padding: 6px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 6px;
          font-size: 12px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          box-sizing: border-box;
        }
        .se-search:focus { outline: none; border-color: var(--primary-color); }
        .se-list {
          flex: 1;
          overflow-y: auto;
          overflow-x: hidden;
        }
        .se-group {
          padding: 6px 12px 4px;
          font-size: 10px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--secondary-text-color, #888);
          position: sticky;
          top: 0;
          background: var(--card-background-color, #fff);
          z-index: 1;
        }
        .se-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 7px 12px;
          cursor: pointer;
          font-size: 13px;
          color: var(--primary-text-color);
          border-left: 3px solid transparent;
          transition: all 0.1s;
        }
        .se-item:hover { background: var(--primary-background-color, #f5f5f5); }
        .se-item.active {
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent);
          border-left-color: var(--primary-color, #03a9f4);
        }
        .se-item-icon { font-size: 14px; flex-shrink: 0; }
        .se-item-name {
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .se-item-badge {
          font-size: 9px;
          padding: 1px 5px;
          border-radius: 8px;
          background: var(--warning-color, #ff9800);
          color: #fff;
          flex-shrink: 0;
        }
        .se-empty {
          padding: 20px 12px;
          text-align: center;
          color: var(--secondary-text-color);
          font-size: 12px;
        }
        .se-footer {
          padding: 8px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          flex-shrink: 0;
          display: flex;
          gap: 6px;
        }
        .se-footer .sc-btn { flex: 1; text-align: center; }
      </style>

      <div class="se-types">
        <button class="se-type-btn active" data-type="">All</button>
        <button class="se-type-btn" data-type="automation">\u2699</button>
        <button class="se-type-btn" data-type="script">\uD83D\uDCDC</button>
        <button class="se-type-btn" data-type="scene">\uD83C\uDFA8</button>
        <button class="se-type-btn" data-type="blueprint">\uD83D\uDCD0</button>
      </div>
      <div class="se-search-wrap">
        <input class="se-search" type="text" placeholder="Search..." autocomplete="off">
      </div>
      <div class="se-list"></div>
      <div class="se-footer">
        <button class="sc-btn sc-btn-primary se-new-btn">+ New</button>
        <button class="sc-btn sc-btn-ghost se-refresh-btn">\u21BB Refresh</button>
      </div>
    `;

    // Type filter buttons
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
    if (listEl) listEl.innerHTML = '<div class="se-empty">Loading...</div>';

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
      listEl.innerHTML = '<div class="se-empty">No items found</div>';
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
      html += `<div class="se-group">${TYPE_ICONS[type] || ""} ${TYPE_LABELS[type] || type} (${items.length})</div>`;
      for (const item of items) {
        const alias = escapeHtml(item.alias || "Unnamed");
        const isActive = this._activeId === `${item.type}:${item.id}`;
        const bpBadge = item.blueprint_based ? '<span class="se-item-badge">BP</span>' : "";
        html += `<div class="se-item${isActive ? " active" : ""}" data-type="${escapeHtml(item.type)}" data-id="${escapeHtml(item.id)}">
          <span class="se-item-icon">${TYPE_ICONS[item.type] || ""}</span>
          <span class="se-item-name">${alias}</span>
          ${bpBadge}
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

    // Warn about blueprint-based automations
    const item = this._items.find((i) => i.type === type && i.id === id);
    if (item?.blueprint_based) {
      const ok = confirm(
        `"${item.alias}" is based on a blueprint.\n\n` +
        "Direct edits will break the blueprint link.\nContinue?"
      );
      if (!ok) return;
    }

    // Visual feedback
    this._activeId = `${type}:${id}`;
    this._renderList();

    try {
      const resp = await callService(this._hass, "smartchain", "get_yaml", { type, id });
      const data = extractResponse(resp, "smartchain.get_yaml");
      if (data.error) return;

      this.dispatchEvent(
        new CustomEvent("select", {
          detail: {
            yaml: data.yaml || "",
            type,
            id,
            alias: item?.alias || "Unnamed",
          },
        })
      );
    } catch {
      // ignore
    }
  }

  /** Highlight an item from outside */
  setActive(type, id) {
    this._activeId = type && id ? `${type}:${id}` : null;
    this._renderList();
  }
}

customElements.define("sc-sidebar-explorer", ScSidebarExplorer);
