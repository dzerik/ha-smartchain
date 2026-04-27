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
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
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
