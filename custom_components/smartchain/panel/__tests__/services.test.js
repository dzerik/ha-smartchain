import { describe, expect, it } from "vitest";

import { escapeHtml } from "../services.js";

/**
 * `escapeHtml` is the panel's only defence on the `innerHTML` surface: every
 * tab interpolates backend-supplied text — tool names, store titles, YAML
 * parse errors — into template literals that are then assigned to
 * `innerHTML`, including into attribute positions (`data-entry="…"`,
 * `title="…"`). These tests pin the five characters it claims to handle, and
 * the two properties that make the result actually safe rather than merely
 * different: the ampersand is escaped *first*, and non-strings are coerced
 * rather than crashing or leaking `undefined` into markup.
 */
describe("escapeHtml", () => {
  it("escapes all five HTML-significant characters", () => {
    expect(escapeHtml("&")).toBe("&amp;");
    expect(escapeHtml("<")).toBe("&lt;");
    expect(escapeHtml(">")).toBe("&gt;");
    expect(escapeHtml('"')).toBe("&quot;");
    expect(escapeHtml("'")).toBe("&#39;");
  });

  it("escapes the ampersand first, so an escape is never re-read as markup", () => {
    // Careful: on an input that is *already* an entity both orders agree —
    // "&lt;" contains no `<`, so only the `&` rule ever fires and the answer is
    // "&amp;lt;" whether that rule runs first or last. These two lines pin the
    // double-escaping shape, but they cannot tell the orders apart.
    expect(escapeHtml("&lt;")).toBe("&amp;lt;");
    expect(escapeHtml("&amp;")).toBe("&amp;amp;");

    // What discriminates is an input that *produces* entities: escape `&` last
    // and it re-escapes the ampersand of every entity the earlier rules just
    // wrote, so `<` reaches the browser as the literal text `&lt;`. A round
    // trip through innerHTML is the strongest way to say that, since the whole
    // claim is about what the browser finally reads.
    const mixed = "<tag> & \"quoted\" 'text'";
    expect(escapeHtml(mixed)).toBe("&lt;tag&gt; &amp; &quot;quoted&quot; &#39;text&#39;");
    const host = document.createElement("div");
    host.innerHTML = escapeHtml(mixed);
    expect(host.textContent).toBe(mixed);
  });

  it("neutralises a script tag and an attribute break-out", () => {
    expect(escapeHtml("<script>alert(1)</script>")).toBe(
      "&lt;script&gt;alert(1)&lt;/script&gt;"
    );
    // The shape that matters for `data-entry="${escapeHtml(id)}"` in tools-tab.
    expect(escapeHtml('" onmouseover="steal()')).toBe(
      "&quot; onmouseover=&quot;steal()"
    );
  });

  it("actually renders as inert text when fed through innerHTML", () => {
    // The unit above is about the string; this is about the guarantee. The
    // browser is the authority on whether the escaping worked, so ask it.
    const host = document.createElement("div");
    const hostile = '<img src=x onerror="boom()">';
    host.innerHTML = `<span title="${escapeHtml(hostile)}">${escapeHtml(hostile)}</span>`;

    expect(host.querySelectorAll("img")).toHaveLength(0);
    expect(host.querySelector("span").textContent).toBe(hostile);
    expect(host.querySelector("span").getAttribute("title")).toBe(hostile);
  });

  it("coerces non-string input instead of throwing", () => {
    // Backends send `null` for an absent optional field; `escapeHtml(null)`
    // must produce something renderable, not a TypeError that takes the whole
    // tab's innerHTML assignment down with it.
    expect(escapeHtml(null)).toBe("null");
    expect(escapeHtml(undefined)).toBe("undefined");
    expect(escapeHtml(42)).toBe("42");
  });

  it("leaves ordinary text — including Cyrillic — untouched", () => {
    expect(escapeHtml("Кухня · sensor.kitchen_temperature")).toBe(
      "Кухня · sensor.kitchen_temperature"
    );
  });
});
