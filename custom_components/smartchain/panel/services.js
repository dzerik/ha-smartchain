/**
 * Helper to call HA services with response.
 * @param {object} hass - HA connection object
 * @param {string} domain
 * @param {string} service
 * @param {object} data
 * @returns {Promise<object>}
 */
export async function callService(hass, domain, service, data) {
  return await hass.connection.sendMessagePromise({
    type: "call_service",
    domain,
    service,
    service_data: data,
    return_response: true,
  });
}

/**
 * Extract service response data, handling HA's nested response format.
 */
export function extractResponse(resp, serviceKey) {
  return resp.response?.[serviceKey] || resp.response || {};
}

/**
 * Escape HTML entities.
 */
export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Collect SmartChain agents from hass.states.
 */
export function getAgents(hass) {
  const agents = [];
  if (!hass) return agents;
  for (const [entityId, state] of Object.entries(hass.states)) {
    if (entityId.startsWith("conversation.") && entityId.includes("smartchain")) {
      agents.push({
        id: entityId,
        name: state.attributes.friendly_name || entityId,
      });
    }
  }
  return agents;
}

/**
 * Collect all available entities from hass.states, sorted by domain.
 */
export function getAllEntities(hass) {
  const entities = [];
  if (!hass) return entities;
  for (const [entityId, state] of Object.entries(hass.states)) {
    if (state.state === "unavailable") continue;
    entities.push({
      id: entityId,
      name: state.attributes.friendly_name || entityId,
      domain: entityId.split(".")[0],
      state: state.state,
    });
  }
  entities.sort((a, b) => a.domain.localeCompare(b.domain) || a.id.localeCompare(b.id));
  return entities;
}

/**
 * Populate a <select> element with options.
 */
export function populateSelect(selectEl, items, placeholder) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML = `<option value="">${placeholder}</option>`;
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name;
    selectEl.appendChild(opt);
  }
  if (current) selectEl.value = current;
}
