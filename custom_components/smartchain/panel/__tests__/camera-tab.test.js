import { afterEach, beforeEach, describe, expect, it } from "vitest";

import "../components/camera-tab.js";
import { fakeHass, flush, mount } from "./harness.js";

/**
 * Accessible names for the camera tab's controls.
 *
 * `<label class="sc-label">Agent</label>` followed by `<select id="ct-agent">`
 * is a caption drawn next to a control, not a label attached to one: nothing in
 * the DOM ties the two together. A screen reader announces "combo box", a voice
 * user cannot say "click Camera", and clicking the word does not focus the
 * field. `for` is what makes the association real, so the test walks every
 * control in the rendered tab rather than naming the three that exist today —
 * a fourth field added without a label fails here too.
 */

const CONTROL_SELECTOR = "input, select, textarea";

/** The accessible name a browser would compute, by the two routes we use. */
function accessibleName(root, control) {
  const aria = control.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim();
  if (!control.id) return "";
  const label = root.querySelector(`label[for="${control.id}"]`);
  return label ? label.textContent.trim() : "";
}

describe("<sc-camera-tab> control labelling", () => {
  let tab;

  beforeEach(() => {
    document.body.innerHTML = "";
    tab = mount("sc-camera-tab");
  });

  it("renders the three controls the tab is made of", () => {
    const controls = [...tab.querySelectorAll(CONTROL_SELECTOR)];
    expect(controls.map((c) => c.id).sort()).toEqual([
      "ct-agent",
      "ct-camera",
      "ct-prompt",
    ]);
  });

  it("gives every control a non-empty accessible name", () => {
    const controls = [...tab.querySelectorAll(CONTROL_SELECTOR)];
    expect(controls.length).toBeGreaterThan(0);

    const unnamed = controls
      .filter((c) => !accessibleName(tab, c))
      .map((c) => c.id || c.outerHTML.slice(0, 60));
    expect(unnamed).toEqual([]);
  });

  it("ties each visible caption to its control with for=", () => {
    // Named individually as well, because the sweep above would also pass if
    // someone replaced the visible captions with invisible aria-labels — which
    // would take the click-the-word-to-focus behaviour away.
    for (const [id, text] of [
      ["ct-agent", "Agent"],
      ["ct-camera", "Camera"],
      ["ct-prompt", "Question / Instruction"],
    ]) {
      const label = tab.querySelector(`label[for="${id}"]`);
      expect(label, `no label[for="${id}"]`).not.toBeNull();
      expect(label.textContent.trim()).toBe(text);
      // htmlFor must point at a control that is really there.
      expect(tab.querySelector(`#${id}`)).not.toBeNull();
    }
  });

  it("has no hardcoded foreground colour over the themable code background", () => {
    // The response pane paints itself on --code-editor-background-color, which
    // Home Assistant resolves to the card background — white on a light theme.
    // A literal light-grey ink there is unreadable, so assert the literal is
    // gone rather than trying to compute contrast in jsdom.
    const style = tab.querySelector("style").textContent;
    expect(style).not.toContain("#d4d4d4");
    expect(style).toContain("var(--primary-text-color");
  });
});

/**
 * The result pane is the tab's one asynchronous output: it arrives long after
 * focus has moved on, so `aria-live` is what is supposed to speak it.
 *
 * The attribute alone proves nothing. `.sc-hidden` is `display: none`, and a
 * node inside a `display:none` subtree is not in the accessibility tree at
 * all — a text change there is invisible to assistive technology, so a live
 * region that is hidden when it is written to announces nothing whatsoever.
 * These tests therefore watch the *writes*: every one of them must land while
 * the region is on screen. Asserting the attribute exists would pass just as
 * happily with the announcement mechanically impossible, which is exactly the
 * state this file used to certify.
 */
describe("<sc-camera-tab> announcing the analysis result", () => {
  /**
   * Record every assignment to the response pane's text, with the visibility
   * of the live region at that exact moment. Synchronous on purpose: a
   * MutationObserver batches, so it would report the state after the whole
   * handler finished and would happily bless a write made while hidden.
   */
  function watchWrites(tab) {
    const region = tab.querySelector("#ct-result");
    const pane = tab.querySelector("#ct-response");
    const writes = [];
    let text = "";
    Object.defineProperty(pane, "textContent", {
      configurable: true,
      get: () => text,
      set(value) {
        text = value;
        writes.push({ value, hidden: region.classList.contains("sc-hidden") });
      },
    });
    return writes;
  }

  async function analyze(answer) {
    const net = fakeHass({ call_service: answer });
    net.hass.states = {
      "camera.front": { state: "idle", attributes: { friendly_name: "Front door" } },
    };
    const tab = mount("sc-camera-tab");
    tab.hass = net.hass;
    const writes = watchWrites(tab);
    tab.querySelector("#ct-camera").value = "camera.front";
    tab.querySelector("#ct-prompt").value = "who is at the door?";
    tab.querySelector("#ct-btn-analyze").dispatchEvent(new Event("click"));
    await flush();
    return { tab, writes };
  }

  // jsdom refuses to run a second element's connectedCallback render while an
  // earlier instance is still in the body, so each test starts from an empty
  // document — the same thing the first describe does.
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("marks the pane as a live region at all", () => {
    // Necessary but nowhere near sufficient — see the tests below.
    const tab = mount("sc-camera-tab");
    expect(tab.querySelector("#ct-result").getAttribute("aria-live")).toBe("polite");
  });

  it("is on screen every time the result text is written", async () => {
    const { tab, writes } = await analyze({
      response: { "smartchain.analyze_image": { response: "A parcel courier." } },
    });

    expect(writes.length).toBeGreaterThan(0);
    // Not "the last write was visible": a write made while hidden is a lost
    // announcement even if the pane is revealed a line later.
    expect(writes.map((write) => write.hidden)).toEqual(writes.map(() => false));
    expect(writes[writes.length - 1].value).toBe("A parcel courier.");
    expect(tab.querySelector("#ct-result").classList.contains("sc-hidden")).toBe(false);
  });

  it("is on screen when a failure is written there too", async () => {
    const { writes } = await analyze(() => {
      throw new Error("Camera unavailable");
    });

    expect(writes.length).toBeGreaterThan(0);
    expect(writes.map((write) => write.hidden)).toEqual(writes.map(() => false));
    expect(writes[writes.length - 1].value).toContain("Camera unavailable");
  });

  it("says something rather than sitting on a stale progress line", async () => {
    // An empty response used to leave the pane hidden and silent; with the
    // region revealed for the run, it would leave "Analyzing…" on screen
    // forever instead. Either way the user is told nothing about what came
    // back, so say it.
    const { writes } = await analyze({ response: { "smartchain.analyze_image": {} } });
    const final = writes[writes.length - 1].value;
    expect(final).not.toMatch(/Analyzing/);
    expect(final).not.toBe("");
    expect(writes.map((write) => write.hidden)).toEqual(writes.map(() => false));
  });
});
