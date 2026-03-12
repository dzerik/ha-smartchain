import { escapeHtml } from "../services.js";

/**
 * <sc-entity-picker> — multi-select entity picker with search and chips.
 *
 * Properties:
 *   .entities = [{id, name, domain, state}, ...]
 *   .selected = ["entity.id", ...]
 *
 * Events: "change" { selected: [...] }
 */
export class ScEntityPicker extends HTMLElement {
  constructor() {
    super();
    this._entities = [];
    this._selected = [];
    this._filter = "";
    this._open = false;
    this._rendered = false;
    this._onDocClick = this._handleDocClick.bind(this);
  }

  set entities(val) { this._entities = val || []; }
  get entities() { return this._entities; }

  set selected(val) {
    this._selected = val || [];
    this._renderChips();
  }
  get selected() { return this._selected; }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    document.addEventListener("click", this._onDocClick);
  }

  disconnectedCallback() {
    document.removeEventListener("click", this._onDocClick);
  }

  _handleDocClick(e) {
    if (!this.querySelector(".ep-wrap")?.contains(e.target)) {
      this._closeDropdown();
    }
  }

  _closeDropdown() {
    const dropdown = this.querySelector(".ep-dropdown");
    if (dropdown) dropdown.classList.remove("open");
    this._open = false;
  }

  _render() {
    this.innerHTML = `
      <style>
        .ep-wrap { position: relative; }
        .ep-search {
          width: 100%;
          padding: 10px 14px 10px 36px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 10px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-size: 14px;
          box-sizing: border-box;
          transition: border-color 0.2s, box-shadow 0.2s;
        }
        .ep-search:focus { outline: none; border-color: var(--primary-color, #03a9f4); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 15%, transparent); }
        .ep-search-icon {
          position: absolute;
          left: 12px;
          top: 12px;
          color: var(--secondary-text-color);
          --mdc-icon-size: 18px;
          pointer-events: none;
        }
        .ep-dropdown {
          position: absolute;
          top: calc(100% + 4px);
          left: 0; right: 0;
          max-height: 280px;
          overflow-y: auto;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 10px;
          z-index: 100;
          box-shadow: 0 8px 24px rgba(0,0,0,0.12);
          display: none;
        }
        .ep-dropdown.open { display: block; }
        .ep-domain {
          padding: 8px 14px;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          color: var(--secondary-text-color);
          background: var(--primary-background-color, #fafafa);
          position: sticky; top: 0;
        }
        .ep-item {
          padding: 9px 14px;
          cursor: pointer;
          font-size: 13px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          transition: background 0.1s;
        }
        .ep-item:hover { background: var(--primary-background-color, #f5f5f5); }
        .ep-item.sel { background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent); }
        .ep-item.sel::after {
          content: '';
          width: 16px; height: 16px;
          border-radius: 50%;
          background: var(--primary-color, #03a9f4);
          display: inline-block;
          flex-shrink: 0;
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z'/%3E%3C/svg%3E");
          background-size: 12px;
          background-position: center;
          background-repeat: no-repeat;
        }
        .ep-item-name { font-weight: 500; }
        .ep-item-id { font-family: var(--code-font-family, monospace); color: var(--secondary-text-color); font-size: 12px; }
        .ep-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
        .ep-chip {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 5px 12px; border-radius: 20px; font-size: 12px;
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
          color: var(--primary-color, #03a9f4); font-weight: 500;
          transition: background 0.15s;
        }
        .ep-chip-x {
          cursor: pointer;
          width: 16px; height: 16px;
          border-radius: 50%;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          line-height: 1;
          transition: background 0.15s;
        }
        .ep-chip-x:hover { background: color-mix(in srgb, var(--primary-color) 25%, transparent); }
        .ep-empty {
          padding: 20px;
          text-align: center;
          color: var(--secondary-text-color);
          font-size: 13px;
        }
      </style>
      <div class="ep-wrap">
        <ha-icon class="ep-search-icon" icon="mdi:magnify"></ha-icon>
        <input type="text" class="ep-search"
          placeholder="Search entities..."
          autocomplete="off">
        <div class="ep-dropdown"></div>
      </div>
      <div class="ep-chips"></div>
    `;

    const input = this.querySelector(".ep-search");
    const dropdown = this.querySelector(".ep-dropdown");

    input.addEventListener("focus", () => {
      this._renderDropdown();
      dropdown.classList.add("open");
      this._open = true;
    });
    input.addEventListener("input", () => {
      this._filter = input.value.toLowerCase();
      this._renderDropdown();
      if (!this._open) {
        dropdown.classList.add("open");
        this._open = true;
      }
    });
  }

  _renderDropdown() {
    const dropdown = this.querySelector(".ep-dropdown");
    if (!dropdown) return;

    const filter = this._filter;
    const filtered = this._entities.filter((e) => {
      const text = `${e.id} ${e.name}`.toLowerCase();
      return !filter || text.includes(filter);
    });
    const limited = filtered.slice(0, 100);

    if (!limited.length) {
      dropdown.innerHTML = '<div class="ep-empty">No entities found</div>';
      return;
    }

    let html = "";
    let lastDomain = "";
    for (const entity of limited) {
      if (entity.domain !== lastDomain) {
        lastDomain = entity.domain;
        html += `<div class="ep-domain">${escapeHtml(entity.domain)}</div>`;
      }
      const sel = this._selected.includes(entity.id) ? " sel" : "";
      html += `<div class="ep-item${sel}" data-eid="${escapeHtml(entity.id)}">
        <span>
          <span class="ep-item-name">${escapeHtml(entity.name)}</span>
          <span class="ep-item-id">${escapeHtml(entity.id)}</span>
        </span>
      </div>`;
    }
    if (filtered.length > 100) {
      html += `<div class="ep-empty">${filtered.length - 100} more results...</div>`;
    }

    dropdown.innerHTML = html;
    dropdown.querySelectorAll(".ep-item").forEach((item) => {
      item.addEventListener("click", () => this._toggleEntity(item.dataset.eid));
    });
  }

  _toggleEntity(eid) {
    if (this._selected.includes(eid)) {
      this._selected = this._selected.filter((x) => x !== eid);
    } else {
      this._selected = [...this._selected, eid];
    }
    this._renderDropdown();
    this._renderChips();
    this.dispatchEvent(new CustomEvent("change", { detail: { selected: this._selected } }));
  }

  _renderChips() {
    const container = this.querySelector(".ep-chips");
    if (!container) return;
    if (!this._selected.length) { container.innerHTML = ""; return; }

    container.innerHTML = this._selected
      .map((eid) => `<span class="ep-chip">${escapeHtml(eid)}<span class="ep-chip-x" data-eid="${escapeHtml(eid)}">&times;</span></span>`)
      .join("");

    container.querySelectorAll(".ep-chip-x").forEach((btn) => {
      btn.addEventListener("click", () => this._toggleEntity(btn.dataset.eid));
    });
  }
}

customElements.define("sc-entity-picker", ScEntityPicker);
