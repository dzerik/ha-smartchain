/**
 * <sc-agents-tab> — agent list and actions. Filled in by Task 6.
 *
 * Properties: .hass
 */
export class ScAgentsTab extends HTMLElement {
  set hass(val) {
    this._hass = val;
  }
}

customElements.define("sc-agents-tab", ScAgentsTab);
