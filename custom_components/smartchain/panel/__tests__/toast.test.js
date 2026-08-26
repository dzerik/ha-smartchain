import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { showToast, toastDuration } from "../services.js";

/**
 * The toast is the panel's only output channel for a failure. Nothing else
 * carries the text: the websocket errors never reach Home Assistant's log, and
 * no tab renders them a second time. So a toast that a screen reader never
 * announces, that cannot be re-read, or that takes a three-line `reload_failed`
 * paragraph away after 3.5 seconds is the same thing as losing the message.
 *
 * These tests pin the created node, not the CSS: the attributes an assistive
 * technology reads, the control a mouse user clicks, and the timer arithmetic.
 */

const container = () => document.querySelector(".sc-toast-container");
const toasts = () => [...document.querySelectorAll(".sc-toast")];

beforeEach(() => {
  document.body.innerHTML = "";
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("showToast — announcement", () => {
  it("puts the toasts in a live region so a screen reader speaks them", () => {
    showToast("Saved", "success");

    expect(container()).not.toBeNull();
    expect(container().getAttribute("aria-live")).toBe("polite");
  });

  it("marks each toast as an alert in its own right", () => {
    showToast("Reload failed", "error");

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].getAttribute("role")).toBe("alert");
  });

  it("keeps the message readable as text, not only as markup", () => {
    showToast("Saved, but the reload failed: bad indent at line 4", "warning");

    expect(toasts()[0].textContent).toContain(
      "Saved, but the reload failed: bad indent at line 4"
    );
  });
});

describe("showToast — dismissing by hand", () => {
  it("offers a named close control", () => {
    showToast("Saved", "success");
    const close = toasts()[0].querySelector("button.sc-toast-close");

    expect(close).not.toBeNull();
    // A bare "✕" glyph is not a name. Without this the button is announced as
    // "button" and there is nothing to tell the user what it closes.
    expect(close.getAttribute("aria-label")).toBeTruthy();
  });

  it("removes the toast when the close control is clicked", () => {
    showToast("Saved", "success");
    toasts()[0].querySelector("button.sc-toast-close").click();

    // The out-animation never fires under jsdom, which is exactly the case the
    // fallback timer exists for — a real browser with reduced motion behaves
    // the same way.
    vi.advanceTimersByTime(1000);
    expect(toasts()).toHaveLength(0);
  });

  it("closes an error by hand even though no timer would", () => {
    showToast("Store did not start", "error");
    vi.advanceTimersByTime(120000);
    expect(toasts()).toHaveLength(1);

    toasts()[0].querySelector("button.sc-toast-close").click();
    vi.advanceTimersByTime(1000);
    expect(toasts()).toHaveLength(0);
  });
});

describe("showToast — how long it stays", () => {
  it("gives a long message more time than a short one", () => {
    const short = toastDuration("Saved");
    const paragraph = toastDuration(
      "Saved, but the reload failed: while parsing a block mapping at line 12, " +
        "column 3 — expected <block end>, but found '-'. The previous tools.yaml " +
        "is still in force and no agent changed."
    );

    expect(paragraph).toBeGreaterThan(short);
  });

  it("never drops below a floor a two-word toast can still be read at", () => {
    expect(toastDuration("")).toBeGreaterThanOrEqual(4000);
    expect(toastDuration("OK")).toBeGreaterThanOrEqual(4000);
  });

  it("caps the wait so one toast cannot sit on the screen for a minute", () => {
    expect(toastDuration("x".repeat(5000))).toBeLessThanOrEqual(20000);
  });

  it("actually uses that duration, and the old flat 3500ms is not enough", () => {
    const message =
      "Saved, but the reload failed: while parsing a block mapping at line 12, " +
      "column 3 — expected <block end>, but found '-'.";
    showToast(message, "warning");

    // The regression this test exists for: at 3.5s the paragraph was already
    // gone, unread and unrecoverable.
    vi.advanceTimersByTime(3500);
    expect(toasts()).toHaveLength(1);

    vi.advanceTimersByTime(toastDuration(message) - 3500 + 1000);
    expect(toasts()).toHaveLength(0);
  });

  it("still auto-hides a short success", () => {
    showToast("Saved", "success");
    vi.advanceTimersByTime(toastDuration("Saved") + 1000);
    expect(toasts()).toHaveLength(0);
  });

  it("honours an explicit duration for a non-error toast", () => {
    showToast("Saved", "success", 9000);
    vi.advanceTimersByTime(8000);
    expect(toasts()).toHaveLength(1);
    vi.advanceTimersByTime(2000);
    expect(toasts()).toHaveLength(0);
  });
});

describe("showToast — errors do not vanish", () => {
  it("leaves an error on screen indefinitely", () => {
    showToast("Analysis failed: connection refused", "error");
    vi.advanceTimersByTime(600000);

    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].textContent).toContain("connection refused");
  });

  it("ignores even an explicit duration on an error", () => {
    showToast("Analysis failed", "error", 100);
    vi.advanceTimersByTime(60000);
    expect(toasts()).toHaveLength(1);
  });

  it("does not hold on to a warning — only an error is unconditional", () => {
    showToast("Saved, but the reload failed", "warning");
    vi.advanceTimersByTime(60000);
    expect(toasts()).toHaveLength(0);
  });
});
