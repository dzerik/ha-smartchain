/**
 * SmartChain Panel — Service utilities & helpers.
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

export function extractResponse(resp, serviceKey) {
  return resp.response?.[serviceKey] || resp.response || {};
}

export function escapeHtml(text) {
  // Escapes &, <, > and both quote characters. Every caller feeds the
  // result into innerHTML, where HTML character references decode back to
  // their literal characters regardless of whether they land in a text
  // node or an attribute value — so escaping quotes here does not make
  // `&quot;` show up literally in visible text, and it is safe to reuse
  // this same function for attribute positions like data-entry="...".
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function getAgents(hass) {
  if (!hass) return [];
  return Object.entries(hass.states)
    .filter(([id]) => id.startsWith("conversation.") && id.includes("smartchain"))
    .map(([id, state]) => ({ id, name: state.attributes.friendly_name || id }));
}

export function populateSelect(selectEl, items, placeholder) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>`;
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name;
    selectEl.appendChild(opt);
  }
  if (current) selectEl.value = current;
}

/* ========== Toast Notification System ========== */

let toastContainer = null;

function ensureToastContainer() {
  if (toastContainer && document.body.contains(toastContainer)) return toastContainer;
  toastContainer = document.createElement("div");
  toastContainer.className = "sc-toast-container";
  document.body.appendChild(toastContainer);
  return toastContainer;
}

export function showToast(message, type = "info", duration = 3500) {
  const container = ensureToastContainer();
  const toast = document.createElement("div");
  toast.className = `sc-toast sc-toast-${type}`;

  const icons = {
    success: "mdi:check-circle",
    error: "mdi:alert-circle",
    info: "mdi:information",
    warning: "mdi:alert",
  };

  toast.innerHTML = `<ha-icon icon="${icons[type] || icons.info}"></ha-icon><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("sc-toast-out");
    toast.addEventListener("animationend", () => toast.remove());
  }, duration);
}

/**
 * Send a SmartChain websocket command and return its result.
 *
 * Throws with the backend's message, which is safe to display — the backend
 * never puts a credential in one.
 */
export async function callWS(hass, type, payload = {}) {
  return await hass.connection.sendMessagePromise({ type, ...payload });
}
