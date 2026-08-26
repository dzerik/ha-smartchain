import { beforeEach, describe, expect, it } from "vitest";

import "../components/camera-tab.js";
import { mount } from "./harness.js";

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

  it("announces the analysis result when it appears", () => {
    // The result arrives after an await, long after focus moved on. Without a
    // live region the text is drawn and never spoken.
    const result = tab.querySelector("#ct-result");
    expect(result).not.toBeNull();
    expect(result.getAttribute("aria-live")).toBe("polite");
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
