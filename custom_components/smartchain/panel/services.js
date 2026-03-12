/**
 * SmartChain Panel — Service utilities & helpers.
 */

/**
 * Call HA service with response.
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
 * Extract service response data from HA's nested format.
 */
export function extractResponse(resp, serviceKey) {
  return resp.response?.[serviceKey] || resp.response || {};
}

/**
 * Escape HTML entities to prevent XSS.
 */
export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

/**
 * Collect SmartChain agents from hass.states.
 */
export function getAgents(hass) {
  if (!hass) return [];
  return Object.entries(hass.states)
    .filter(([id]) => id.startsWith("conversation.") && id.includes("smartchain"))
    .map(([id, state]) => ({ id, name: state.attributes.friendly_name || id }));
}

/**
 * Collect all available entities from hass.states.
 */
export function getAllEntities(hass) {
  if (!hass) return [];
  return Object.entries(hass.states)
    .filter(([, state]) => state.state !== "unavailable")
    .map(([id, state]) => ({
      id,
      name: state.attributes.friendly_name || id,
      domain: id.split(".")[0],
      state: state.state,
    }))
    .sort((a, b) => a.domain.localeCompare(b.domain) || a.id.localeCompare(b.id));
}

/**
 * Populate a <select> element with options.
 */
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

/**
 * Show a toast notification.
 * @param {string} message
 * @param {"success"|"error"|"info"|"warning"} type
 * @param {number} duration — ms, default 3500
 */
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

/* ========== Confirm Dialog ========== */

/**
 * Show a confirm dialog (replaces native confirm()).
 * @param {string} title
 * @param {string} message
 * @param {string} confirmLabel
 * @param {string} confirmClass — "sc-btn-danger" | "sc-btn-primary" etc.
 * @returns {Promise<boolean>}
 */
export function showConfirm(title, message, confirmLabel = "Continue", confirmClass = "sc-btn-primary") {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;";
    overlay.innerHTML = `
      <div style="background:var(--card-background-color,#1e1e1e);border-radius:12px;padding:28px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);">
        <h3 style="margin:0 0 12px;font-size:18px;font-weight:600;color:var(--primary-text-color,#fff);">${escapeHtml(title)}</h3>
        <p style="margin:0 0 24px;font-size:14px;color:var(--secondary-text-color,#aaa);line-height:1.5;">${escapeHtml(message)}</p>
        <div style="display:flex;justify-content:flex-end;gap:10px;">
          <button class="sc-dialog-cancel" style="padding:8px 18px;border-radius:8px;border:1px solid var(--divider-color,#444);background:transparent;color:var(--primary-text-color,#fff);cursor:pointer;font-size:14px;">Cancel</button>
          <button class="sc-dialog-confirm" style="padding:8px 18px;border-radius:8px;border:none;background:${confirmClass === "sc-btn-warn" ? "var(--error-color,#f44336)" : "var(--primary-color,#03a9f4)"};color:#fff;cursor:pointer;font-size:14px;">${escapeHtml(confirmLabel)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const cleanup = (result) => {
      overlay.remove();
      resolve(result);
    };

    overlay.querySelector(".sc-dialog-cancel").addEventListener("click", () => cleanup(false));
    overlay.querySelector(".sc-dialog-confirm").addEventListener("click", () => cleanup(true));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) cleanup(false); });
  });
}
