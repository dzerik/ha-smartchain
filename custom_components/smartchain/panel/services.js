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
  // Identify SmartChain agents by the integration that owns them, never by a
  // substring of the entity id. An agent's entity id comes from its title,
  // which is the model name — `conversation.gigachat_2_max` — so the old
  // `id.includes("smartchain")` test missed every normally-named agent and
  // matched only the ones whose title happened to fall back to a ULID.
  const registry = hass.entities || {};
  const byPlatform = Object.entries(hass.states)
    .filter(([id]) => id.startsWith("conversation."))
    .filter(([id]) => registry[id] && registry[id].platform === "smartchain");

  // `hass.entities` is present in every supported frontend, but if it is ever
  // missing the substring test is better than an empty list.
  const chosen = byPlatform.length
    ? byPlatform
    : Object.entries(hass.states).filter(
        ([id]) => id.startsWith("conversation.") && id.includes("smartchain")
      );

  return chosen.map(([id, state]) => ({
    id,
    name: state.attributes.friendly_name || id,
  }));
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

/** Floor: even "Saved" needs long enough to notice something appeared. */
const TOAST_MIN_MS = 4000;
/** Ceiling: no single toast should own a corner of the screen for a minute. */
const TOAST_MAX_MS = 20000;
/** Roughly 200 words per minute of Cyrillic or Latin prose, plus a look-up cost. */
const TOAST_MS_PER_CHAR = 55;

/** How long `message` needs to be readable, in milliseconds. */
export function toastDuration(message) {
  const chars = String(message ?? "").length;
  return Math.min(TOAST_MAX_MS, TOAST_MIN_MS + chars * TOAST_MS_PER_CHAR);
}

function ensureToastContainer() {
  if (toastContainer && document.body.contains(toastContainer)) return toastContainer;
  toastContainer = document.createElement("div");
  toastContainer.className = "sc-toast-container";
  // The container is the live region: it exists before any toast does, which is
  // what lets an assistive technology notice the insertion at all. Each toast
  // additionally carries role="alert" so it is announced as its own message
  // rather than as a re-reading of the whole stack.
  toastContainer.setAttribute("aria-live", "polite");
  toastContainer.setAttribute("aria-atomic", "false");
  document.body.appendChild(toastContainer);
  return toastContainer;
}

/**
 * Show a toast.
 *
 * The toast is the only place a panel failure is ever written down — it is not
 * in Home Assistant's log and no tab re-renders it — so three rules follow:
 * the text stays up long enough to read, an error stays up until it is
 * dismissed, and there is always a way to dismiss it.
 *
 * @param {string} message text to show (escaped before it reaches the DOM)
 * @param {"info"|"success"|"warning"|"error"} type
 * @param {number|null} duration override in ms; ignored for `error`
 * @returns {HTMLElement} the toast node
 */
export function showToast(message, type = "info", duration = null) {
  const container = ensureToastContainer();
  const toast = document.createElement("div");
  toast.className = `sc-toast sc-toast-${type}`;
  toast.setAttribute("role", "alert");

  const icons = {
    success: "mdi:check-circle",
    error: "mdi:alert-circle",
    info: "mdi:information",
    warning: "mdi:alert",
  };

  toast.innerHTML =
    `<ha-icon icon="${icons[type] || icons.info}"></ha-icon>` +
    `<span class="sc-toast-text">${escapeHtml(message)}</span>` +
    `<button type="button" class="sc-toast-close" aria-label="Dismiss notification" title="Dismiss">✕</button>`;
  container.appendChild(toast);

  let timer = null;
  const dismiss = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    toast.classList.add("sc-toast-out");
    // `animationend` is the graceful path. It never fires when the animation is
    // suppressed — prefers-reduced-motion, a backgrounded tab — so arm a
    // fallback slightly longer than the 0.25s out-animation and let whichever
    // arrives first take the node away. Without it a dismissed toast would
    // simply stay on screen.
    toast.addEventListener("animationend", () => toast.remove());
    setTimeout(() => toast.remove(), 400);
  };
  toast.querySelector(".sc-toast-close").addEventListener("click", dismiss);

  // An error is never recoverable once it scrolls away, so it waits for the
  // reader. Everything else is a confirmation and can time out.
  if (type !== "error") {
    timer = setTimeout(dismiss, duration ?? toastDuration(message));
  }
  return toast;
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
