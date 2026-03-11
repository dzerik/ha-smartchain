/**
 * <sc-entity-picker> — multi-select entity picker with search and chips.
 *
 * Properties:
 *   .entities = [{id, name, domain, state}, ...]  — all available entities
 *   .selected = ["entity.id", ...]                 — selected entity_ids (two-way)
 *
 * Events:
 *   "change" — fired when selection changes, detail = { selected: [...] }
 */
export class ScEntityPicker extends HTMLElement {
  constructor() {
    super();
    this._entities = [];
    this._selected = [];
    this._filter = "";
    this._open = false;
    this._rendered = false;
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
  }

  _render() {
    this.innerHTML = `
      <style>
        .ep-wrap { position: relative; }
        .ep-search {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color);
          font-size: 14px;
          box-sizing: border-box;
        }
        .ep-search:focus { outline: none; border-color: var(--primary-color, #03a9f4); }
        .ep-dropdown {
          position: absolute;
          top: 100%;
          left: 0; right: 0;
          max-height: 260px;
          overflow-y: auto;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 0 0 8px 8px;
          z-index: 100;
          box-shadow: 0 4px 12px rgba(0,0,0,0.15);
          display: none;
        }
        .ep-dropdown.open { display: block; }
        .ep-domain {
          padding: 6px 12px;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          color: var(--secondary-text-color);
          background: var(--primary-background-color, #fafafa);
          position: sticky; top: 0;
        }
        .ep-item {
          padding: 7px 12px;
          cursor: pointer;
          font-size: 13px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .ep-item:last-child { border-bottom: none; }
        .ep-item:hover { background: var(--primary-background-color, #f5f5f5); }
        .ep-item.sel { background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent); }
        .ep-item-name { font-weight: 500; }
        .ep-item-id { font-family: var(--code-font-family, monospace); color: var(--secondary-text-color); font-size: 12px; }
        .ep-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
        .ep-chip {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 4px 10px; border-radius: 16px; font-size: 12px;
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 15%, transparent);
          color: var(--primary-color, #03a9f4); font-weight: 500;
        }
        .ep-chip-x { cursor: pointer; font-size: 14px; line-height: 1; opacity: 0.7; }
        .ep-chip-x:hover { opacity: 1; }
      </style>
      <div class="ep-wrap">
        <input type="text" class="ep-search"
          placeholder="Search entities... (e.g. light, kitchen, sensor)"
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
      dropdown.classList.add("open");
      this._open = true;
    });
    document.addEventListener("click", (e) => {
      if (!this.querySelector(".ep-wrap")?.contains(e.target)) {
        dropdown.classList.remove("open");
        this._open = false;
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
    let html = "";
    let lastDomain = "";
    for (const entity of limited) {
      if (entity.domain !== lastDomain) {
        lastDomain = entity.domain;
        html += `<div class="ep-domain">${entity.domain}</div>`;
      }
      const sel = this._selected.includes(entity.id) ? " sel" : "";
      const eid = entity.id.replace(/"/g, "&quot;");
      const ename = (entity.name || "").replace(/</g, "&lt;");
      html += `<div class="ep-item${sel}" data-eid="${eid}">
        <span class="ep-item-name">${ename}</span>
        <span class="ep-item-id">${eid}</span>
      </div>`;
    }
    if (filtered.length > 100) {
      html += `<div class="ep-domain">${filtered.length - 100} more...</div>`;
    }
    dropdown.innerHTML = html;
    dropdown.querySelectorAll(".ep-item").forEach((item) => {
      item.addEventListener("click", () => {
        const eid = item.dataset.eid;
        if (this._selected.includes(eid)) {
          this._selected = this._selected.filter((x) => x !== eid);
        } else {
          this._selected = [...this._selected, eid];
        }
        this._renderDropdown();
        this._renderChips();
        this.dispatchEvent(new CustomEvent("change", { detail: { selected: this._selected } }));
      });
    });
  }

  _renderChips() {
    const container = this.querySelector(".ep-chips");
    if (!container) return;
    if (!this._selected.length) { container.innerHTML = ""; return; }
    container.innerHTML = this._selected
      .map((eid) => `<span class="ep-chip">${eid.replace(/</g, "&lt;")}<span class="ep-chip-x" data-eid="${eid}">&times;</span></span>`)
      .join("");
    container.querySelectorAll(".ep-chip-x").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._selected = this._selected.filter((x) => x !== btn.dataset.eid);
        this._renderChips();
        this._renderDropdown();
        this.dispatchEvent(new CustomEvent("change", { detail: { selected: this._selected } }));
      });
    });
  }
}

customElements.define("sc-entity-picker", ScEntityPicker);
