import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../smartchain-panel.js";
import { fakeHass, flush, mount } from "./harness.js";

/**
 * The shell's job here is one line long — `body.innerHTML = "<tab>"` — and that
 * line used to run unconditionally on every tab click, including a click on the
 * tab already open. Anything a user had half-filled in was gone, with no
 * question asked and nothing to undo it. The information was already in the
 * panel (the tools tab computes it to grey out its Save button); it just never
 * reached the one place that destroys the DOM.
 */

const OVERVIEW = {
  entries: [
    {
      entry_id: "entry-1",
      title: "GigaChat",
      engine_label: "GigaChat",
      supports_embeddings: false,
      agents: [
        {
          subentry_id: "sub-1",
          title: "Kitchen",
          model: "GigaChat-2-Max",
          tool_count: 1,
          tool_total: 3,
        },
      ],
    },
  ],
};

const AGENT_SCHEMA = {
  "smartchain/agent/schema": {
    schema: [{ name: "prompt", selector: { text: {} } }],
    data: { prompt: "you are helpful" },
    labels: { prompt: "Prompt" },
  },
};

let confirmSpy;

beforeEach(() => {
  // jsdom has no dialogs; every test states outright what the user answered.
  confirmSpy = vi.fn(() => false);
  globalThis.confirm = confirmSpy;
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

async function bootPanel(extra = {}) {
  const net = fakeHass({
    "smartchain/overview": OVERVIEW,
    ...AGENT_SCHEMA,
    ...extra,
  });
  net.hass.user = { is_admin: true };
  const panel = mount("smartchain-panel");
  panel.panel = { config: { version: "9.9.9" } };
  panel.hass = net.hass;
  await flush();
  return { net, panel };
}

/** The tab-bar button with this label. */
function tabButton(panel, label) {
  const button = [...panel.querySelectorAll(".sc-tab")].find((b) => b.textContent === label);
  expect(button, `no "${label}" tab`).not.toBeUndefined();
  return button;
}

async function clickTab(panel, label) {
  tabButton(panel, label).dispatchEvent(new Event("click"));
  await flush();
}

/** Open the agent create form and type into it, returning the live form. */
async function openDirtyAgentForm(panel) {
  panel.querySelector("sc-agents-tab .sc-add").dispatchEvent(new Event("click"));
  await flush();
  const form = panel.querySelector("sc-config-form");
  expect(form).not.toBeNull();
  form
    .querySelector("ha-form")
    .dispatchEvent(new CustomEvent("value-changed", { detail: { value: { prompt: "half typed" } } }));
  expect(form.hasUnsavedChanges).toBe(true);
  return form;
}

describe("smartchain-panel: leaving a tab with unsaved edits", () => {
  it("asks first, and stays put when the answer is no", async () => {
    const { panel } = await bootPanel();
    const form = await openDirtyAgentForm(panel);

    confirmSpy.mockReturnValue(false);
    await clickTab(panel, "Camera");

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    // The question has to name what is at stake, or it is just an obstacle.
    expect(confirmSpy.mock.calls[0][0]).toMatch(/unsaved/i);

    // Not "a form is present" — the same form node, still holding the text.
    expect(panel.querySelector("sc-config-form")).toBe(form);
    expect(form.isConnected).toBe(true);
    expect(form._data).toEqual({ prompt: "half typed" });
    expect(panel.querySelector("sc-camera-tab")).toBeNull();
    // And the tab bar agrees with what is on screen.
    expect(tabButton(panel, "Agents").getAttribute("aria-selected")).toBe("true");
    expect(tabButton(panel, "Camera").getAttribute("aria-selected")).toBe("false");
  });

  it("leaves when the answer is yes", async () => {
    const { panel } = await bootPanel();
    await openDirtyAgentForm(panel);

    confirmSpy.mockReturnValue(true);
    await clickTab(panel, "Camera");

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(panel.querySelector("sc-camera-tab")).not.toBeNull();
    expect(panel.querySelector("sc-agents-tab")).toBeNull();
    expect(tabButton(panel, "Camera").getAttribute("aria-selected")).toBe("true");
  });

  it("asks nothing when there is nothing to lose", async () => {
    // A confirmation on every tab click is a confirmation nobody reads.
    const { panel } = await bootPanel();
    await clickTab(panel, "Camera");

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(panel.querySelector("sc-camera-tab")).not.toBeNull();
  });

  it("asks nothing for an open form the user has not typed into", async () => {
    const { panel } = await bootPanel();
    panel.querySelector("sc-agents-tab .sc-add").dispatchEvent(new Event("click"));
    await flush();
    expect(panel.querySelector("sc-config-form")).not.toBeNull();

    await clickTab(panel, "Camera");
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(panel.querySelector("sc-camera-tab")).not.toBeNull();
  });

  it("never blocks on a tab that has no such state at all", async () => {
    // <sc-camera-tab> answers nothing to `hasUnsavedChanges`. A shell that
    // treated "no answer" as "maybe" would ask on every click on those tabs.
    const { panel } = await bootPanel();
    await clickTab(panel, "Camera");
    confirmSpy.mockClear();

    await clickTab(panel, "Agents");
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(panel.querySelector("sc-agents-tab")).not.toBeNull();
  });

  it("guards the keyboard route too", async () => {
    // ArrowLeft/ArrowRight on the tab bar go through the same door as a click,
    // and would otherwise be an unguarded way to lose the same edit.
    const { panel } = await bootPanel();
    const form = await openDirtyAgentForm(panel);

    panel
      .querySelector(".sc-tabs")
      .dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await flush();

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(panel.querySelector("sc-config-form")).toBe(form);
    // Focus follows the selection, so a declined move must not take it either:
    // the roving tabindex would otherwise leave focus on a button that is not
    // the selected tab, and the next arrow key would count from the wrong one.
    expect(document.activeElement).not.toBe(tabButton(panel, "Stores"));
  });
});

describe("smartchain-panel: re-selecting the tab already open", () => {
  it("does not rebuild it, and does not ask about it", async () => {
    // Clicking the active tab is a no-op the user expects to be free. It used
    // to be the cheapest way to destroy a half-filled form.
    const { panel } = await bootPanel();
    const form = await openDirtyAgentForm(panel);
    const tab = panel.querySelector("sc-agents-tab");

    await clickTab(panel, "Agents");

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(panel.querySelector("sc-agents-tab")).toBe(tab);
    expect(panel.querySelector("sc-config-form")).toBe(form);
    expect(form._data).toEqual({ prompt: "half typed" });
  });

  it("survives the tab list being recomputed while a form is open", async () => {
    // `_refreshTabs` fires whenever the visible set changes — the Embeddings
    // tab appearing once the overview lands is the everyday case. It re-selects
    // the active tab, which used to mean rebuilding it.
    const { panel, net } = await bootPanel();
    const form = await openDirtyAgentForm(panel);

    panel._overview = {
      entries: [{ ...OVERVIEW.entries[0], supports_embeddings: true }],
    };
    panel.hass = { ...net.hass };
    await flush();

    expect(tabButton(panel, "Embeddings")).not.toBeUndefined();
    expect(panel.querySelector("sc-config-form")).toBe(form);
    expect(form._data).toEqual({ prompt: "half typed" });
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

describe("smartchain-panel: a tab that disappears under the user", () => {
  it("takes them with it rather than asking a question they cannot answer", async () => {
    // Admin status resolving to false removes every admin tab. That is not
    // navigation the user chose, so declining is not on offer: honouring a "no"
    // would leave a non-admin sitting on the Agents tab. The edit is lost, and
    // that is the lesser harm — recorded here so it is a decision, not a gap.
    const { panel, net } = await bootPanel();
    await openDirtyAgentForm(panel);

    panel.hass = { ...net.hass, user: { is_admin: false } };
    await flush();

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(panel.querySelector("sc-camera-tab")).not.toBeNull();
    expect(panel.querySelector("sc-agents-tab")).toBeNull();
    expect(tabButton(panel, "Camera").getAttribute("aria-selected")).toBe("true");
  });
});

describe("smartchain-panel: closing the browser tab", () => {
  it("stops the unload while an edit is unsaved", async () => {
    const { panel } = await bootPanel();
    await openDirtyAgentForm(panel);

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not stop it otherwise", async () => {
    await bootPanel();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("stops listening once the panel is gone", async () => {
    // Home Assistant tears the panel out of the DOM when the user navigates to
    // another page. A listener left behind would block that page's unload over
    // a form that no longer exists.
    const { panel } = await bootPanel();
    await openDirtyAgentForm(panel);
    panel.remove();

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

/**
 * The guard is not the Agents tab's guard — it belongs to every tab that hosts
 * <sc-config-form>, which is five of the six. It used to be one getter on
 * <sc-agents-tab>, so Embeddings, Stores, Settings and Tools each threw an
 * unsaved form away in silence while the shell's own docstring described the
 * protection as complete.
 *
 * These tests drive the real tabs, not a stub: a shell that reads the answer
 * off the tab element alone passes for Agents and fails for the other three,
 * which is precisely the shape of the hole.
 */
const FORM_SCHEMA = {
  schema: [{ name: "prompt", selector: { text: {} } }],
  data: { prompt: "stored on the server" },
  labels: { prompt: "Prompt" },
};

/** An overview rich enough that every form-hosting tab has something to show. */
const FORM_OVERVIEW = {
  entries: [{ ...OVERVIEW.entries[0], supports_embeddings: true, stores: [], embeddings: [] }],
};

/**
 * Each form-hosting tab in this lane, and how a form is opened on it. Settings
 * needs no control: with a single configured entry it paints the form itself.
 */
const FORM_HOSTS = [
  { label: "Agents", open: ".sc-add" },
  { label: "Embeddings", open: ".sc-add" },
  { label: "Stores", open: ".sc-add" },
  { label: "Settings", open: null },
];

async function bootWithForms() {
  const net = fakeHass({
    "smartchain/overview": FORM_OVERVIEW,
    "smartchain/agent/schema": FORM_SCHEMA,
    "smartchain/embeddings/schema": FORM_SCHEMA,
    "smartchain/store/schema": { ...FORM_SCHEMA, embeddings_available: ["An embeddings binding"] },
    "smartchain/store/status": { stores: [], shadowed_yaml: [] },
    "smartchain/settings/get": FORM_SCHEMA,
  });
  net.hass.user = { is_admin: true };
  const panel = mount("smartchain-panel");
  panel.hass = net.hass;
  await flush();
  return { net, panel };
}

/** Open the form on `host` and type into it. Returns the live form. */
async function dirtyFormOn(panel, host) {
  await clickTab(panel, host.label);
  if (host.open) {
    // Only the selected tab is in the DOM, so this reaches that tab's control.
    const control = panel.querySelector(host.open);
    expect(control, `no "${host.open}" on the ${host.label} tab`).not.toBeNull();
    control.dispatchEvent(new Event("click"));
    await flush();
  }
  const form = panel.querySelector("sc-config-form");
  expect(form, `the ${host.label} tab put no form on screen`).not.toBeNull();
  form
    .querySelector("ha-form")
    .dispatchEvent(new CustomEvent("value-changed", { detail: { value: { prompt: "half typed" } } }));
  expect(form.hasUnsavedChanges, `the ${host.label} form did not go dirty`).toBe(true);
  return form;
}

describe("smartchain-panel: every tab that hosts a form is guarded", () => {
  for (const host of FORM_HOSTS) {
    it(`asks before it throws away the ${host.label} tab's unsaved form`, async () => {
      const { panel } = await bootWithForms();
      const form = await dirtyFormOn(panel, host);
      confirmSpy.mockClear();
      confirmSpy.mockReturnValue(false);

      await clickTab(panel, "Camera");

      expect(confirmSpy).toHaveBeenCalledTimes(1);
      // And names the tab the edit is on, not just "a tab".
      expect(confirmSpy.mock.calls[0][0]).toContain(host.label);
      expect(panel.querySelector("sc-config-form")).toBe(form);
      expect(form._data).toEqual({ prompt: "half typed" });
      expect(panel.querySelector("sc-camera-tab")).toBeNull();
    });

    it(`asks nothing about an untouched form on the ${host.label} tab`, async () => {
      // The other half: a guard that answered "maybe" for any open form would
      // put a question in front of every user who merely looked at one.
      const { panel } = await bootWithForms();
      await clickTab(panel, host.label);
      if (host.open) {
        panel.querySelector(host.open).dispatchEvent(new Event("click"));
        await flush();
      }
      expect(panel.querySelector("sc-config-form")).not.toBeNull();
      confirmSpy.mockClear();

      await clickTab(panel, "Camera");

      expect(confirmSpy).not.toHaveBeenCalled();
      expect(panel.querySelector("sc-camera-tab")).not.toBeNull();
    });
  }

  it("still lets a tab answer for state that is not in a form", async () => {
    // <sc-tools-tab>'s tools.yaml editor is a plain <textarea>: its unsaved
    // text belongs to no <sc-config-form>, so the tab has to say so itself.
    // Asserted on a mounted tab element rather than on tools-tab, because the
    // contract is the shell's — any tab may expose the getter.
    const { panel } = await bootWithForms();
    await clickTab(panel, "Camera");
    const camera = panel.querySelector("sc-camera-tab");
    expect(camera.querySelector("sc-config-form")).toBeNull();
    Object.defineProperty(camera, "hasUnsavedChanges", { configurable: true, get: () => true });

    confirmSpy.mockClear();
    confirmSpy.mockReturnValue(false);
    await clickTab(panel, "Agents");

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain("Camera");
    expect(panel.querySelector("sc-camera-tab")).toBe(camera);
  });

  it("stops the browser unload for a form on a tab that is not Agents", async () => {
    // beforeunload reads the same answer, so a hole in one is a hole in both.
    const { panel } = await bootWithForms();
    await dirtyFormOn(panel, { label: "Settings", open: null });

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});
