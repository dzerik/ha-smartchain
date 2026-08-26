import { beforeAll, describe, expect, it } from "vitest";

import { SC_STYLES } from "../styles.js";

/**
 * The panel's stylesheet, read through a real CSS parser rather than as a
 * string.
 *
 * jsdom does no layout, so nothing here can measure a contrast ratio or an
 * overflow. What it *can* do is prove which declaration lives in which rule —
 * which is the whole of both defects below:
 *
 *  - a literal ink (`#d4d4d4`) painted on a background the theme controls, so
 *    the pair only happens to work on a dark theme and reads at about 1.3:1 on
 *    a light one;
 *  - a tab strip that is `display: flex` with no `overflow-x`, so once the tabs
 *    are wider than the window the ones past the edge are simply unreachable.
 */

let sheet;

/**
 * Every style rule in the sheet, including the ones inside @media blocks.
 *
 * Note `rule.cssRules` is truthy on a plain style rule under jsdom (an empty
 * list), so the recursion has to key off `media`; keying off `cssRules` made
 * this walk return nothing at all and the sweep below passed vacuously.
 */
function allRules(node = sheet) {
  const out = [];
  for (const rule of node.cssRules) {
    if (rule.media) out.push(...allRules(rule));
    else if (rule.selectorText) out.push(rule);
  }
  return out;
}

/** The top-level rule with exactly this selector. */
function rule(selector) {
  const found = [...sheet.cssRules].filter((r) => r.selectorText === selector);
  expect(found.length, `expected exactly one rule for ${selector}`).toBe(1);
  return found[0];
}

/** The rule with this selector inside the given @media condition. */
function mediaRule(condition, selector) {
  const blocks = [...sheet.cssRules].filter(
    (r) => r.media && r.media.mediaText.includes(condition)
  );
  expect(blocks.length, `no @media block for ${condition}`).toBeGreaterThan(0);
  const found = blocks
    .flatMap((b) => [...b.cssRules])
    .filter((r) => r.selectorText === selector);
  expect(
    found.length,
    `no rule ${selector} inside @media ${condition}`
  ).toBeGreaterThan(0);
  return found[0];
}

const prop = (r, name) => r.style.getPropertyValue(name);

beforeAll(() => {
  const el = document.createElement("style");
  el.textContent = SC_STYLES;
  document.head.appendChild(el);
  sheet = el.sheet;
  // Guard the guard: if the parser silently swallowed the sheet, every
  // assertion below would pass vacuously.
  expect(sheet.cssRules.length).toBeGreaterThan(50);
});

describe("contrast — no literal ink on a themable ground", () => {
  it("has dropped the hardcoded code-editor palette entirely", () => {
    // Home Assistant resolves --code-editor-background-color from the theme, so
    // any literal paired with it is a coin flip. Both halves of the old pair go.
    // Comments are stripped first: the fix's own comment names the hex it
    // replaced, and prose is not ink.
    const declarations = SC_STYLES.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(declarations).not.toContain("#d4d4d4");
    expect(declarations).not.toContain("#1e1e1e");
    expect(declarations).not.toContain("#6a6a6a");
  });

  it("paints the tools editor with the theme's own text colour", () => {
    const r = rule(".sc-tools-editor");
    expect(prop(r, "color")).toContain("--primary-text-color");
  });

  it("gives that editor a background that falls back with the same theme", () => {
    // If --code-editor-background-color is unset the fallback must still be a
    // theme value, not a fixed dark slab: a fixed dark slab under a themed ink
    // reproduces the same unreadable pair from the other direction.
    const bg = prop(rule(".sc-tools-editor"), "background");
    expect(bg).toContain("--code-editor-background-color");
    expect(bg).toContain("--card-background-color");
  });

  it("themes the editor placeholder too", () => {
    expect(prop(rule(".sc-tools-editor::placeholder"), "color")).toContain(
      "--secondary-text-color"
    );
  });

  it("themes the help panel's code sample, which used the same pair", () => {
    expect(prop(rule(".sc-tools-help-body pre code"), "color")).toContain(
      "--primary-text-color"
    );
    const bg = prop(rule(".sc-tools-help-body pre"), "background");
    expect(bg).toContain("--code-editor-background-color");
    expect(bg).toContain("--card-background-color");
  });

  it("leaves no other literal colour sitting on a themable code ground", () => {
    // A sweep, so the next pane added over the code background cannot quietly
    // repeat the mistake. White-on-brand (.sc-btn, the toasts) is deliberate
    // and never sits on the code background, so it is out of this set.
    // The parser normalises `#d4d4d4` to `rgb(212, 212, 212)`, so "literal"
    // means "resolves without asking the theme" — anything with no var().
    const withCodeGround = allRules().filter((r) =>
      /--code-editor-background-color/.test(r.style.cssText)
    );
    expect(withCodeGround.length).toBeGreaterThan(0);

    const offenders = withCodeGround
      .filter((r) => {
        const c = prop(r, "color").trim();
        return c !== "" && !c.includes("var(");
      })
      .map((r) => `${r.selectorText} { color: ${prop(r, "color")} }`);
    expect(offenders).toEqual([]);
  });
});

describe("tab strip on a narrow screen", () => {
  it("scrolls sideways instead of clipping the tabs past the edge", () => {
    expect(prop(rule(".sc-tabs"), "overflow-x")).toBe("auto");
  });

  it("lets the strip shrink below its content so scrolling can happen at all", () => {
    // A flex item defaults to min-width:auto, which is its content width — so
    // `flex: 1` alone makes the strip refuse to shrink and push the version
    // label out of the window rather than scroll. overflow-x is useless
    // without this.
    const r = rule(".sc-tabs-row .sc-tabs");
    expect(prop(r, "min-width")).toBe("0px");
  });

  it("keeps each tab at its natural width instead of squeezing the labels", () => {
    const r = rule(".sc-tab");
    expect(prop(r, "flex")).toBe("0 0 auto");
    expect(prop(r, "white-space")).toBe("nowrap");
  });

  it("does not let the version label be crushed by the strip beside it", () => {
    expect(prop(rule(".sc-version"), "flex-shrink")).toBe("0");
  });

  it("stacks the two-up form rows on a phone", () => {
    // The camera tab puts Agent and Camera side by side; at 320px each select
    // is ~140px and the option text is unreadable.
    expect(prop(mediaRule("600px", ".sc-row"), "flex-direction")).toBe("column");
  });

  it("trims the page gutters at the same breakpoint", () => {
    // "trims" means smaller than the desktop value, not merely "a padding is
    // declared" — declaring the same 24px would satisfy a truthiness check and
    // change nothing on the phone.
    const firstPx = (r) => parseFloat(prop(r, "padding"));
    expect(parseFloat(prop(rule(".sc-tab-body"), "padding"))).toBe(24);
    expect(parseFloat(prop(rule(".sc-card"), "padding"))).toBe(28);

    expect(firstPx(mediaRule("600px", ".sc-tab-body"))).toBeLessThan(24);
    expect(firstPx(mediaRule("600px", ".sc-card"))).toBeLessThan(28);
  });
});

describe("toast styling follows the toast markup", () => {
  it("styles the close control the markup now creates", () => {
    const r = rule(".sc-toast-close");
    expect(prop(r, "cursor")).toBe("pointer");
    // It sits on a solid brand background; inheriting keeps it legible on all
    // four toast types without repeating any of them.
    expect(prop(r, "color")).toBe("inherit");
  });

  it("gives the close control a visible keyboard focus ring", () => {
    const r = rule(".sc-toast-close:focus-visible");
    const outline = prop(r, "outline");
    // `toBeTruthy()` was the first version of this assertion and `outline: none`
    // sailed straight through it — "none" is a truthy string. The ring has to
    // have a width, and it must not be the keyword that removes it.
    expect(outline).not.toBe("none");
    expect(outline).toMatch(/\d+px/);
  });

  it("lets a long message wrap rather than widen the toast off-screen", () => {
    const r = rule(".sc-toast-text");
    expect(prop(r, "min-width")).toBe("0px");
    expect(prop(r, "overflow-wrap")).toBe("anywhere");
  });

  it("keeps a stack of undismissed errors inside the viewport", () => {
    // Errors no longer time out, so the stack can grow without bound. The cap
    // has to be relative to the viewport — `max-height: none` is truthy and
    // caps nothing, and a fixed pixel cap is wrong on some other screen.
    const r = rule(".sc-toast-container");
    expect(prop(r, "max-height")).toContain("100vh");
    expect(prop(r, "max-width")).toContain("100vw");
    expect(prop(r, "overflow-y")).toBe("auto");
  });
});
