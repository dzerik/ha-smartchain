import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../components/tools-tab.js";
import { fakeHass, flush, mount } from "./harness.js";

const ON_DISK = "tools:\n  - name: on_disk\n";
const DISK_HASH = "hash-of-the-file-as-loaded";

/**
 * Everything the tab asks for while it boots. Individual tests override the
 * one command they are about.
 */
function handlers(extra = {}) {
  return {
    "smartchain/tools/get": {
      path: "/config/smartchain/tools.yaml",
      text: ON_DISK,
      exists: true,
      error: null,
      hash: DISK_HASH,
      backup_exists: false,
    },
    "smartchain/tool/list": { tools: [], shadowed_yaml: [] },
    "smartchain/tool/presets": { presets: [] },
    ...extra,
  };
}

/** Mount the tab, give it an entry and a hass, and let it finish booting. */
async function boot(extra = {}) {
  const net = fakeHass(handlers(extra));
  const tab = mount("sc-tools-tab");
  tab.entries = [{ entry_id: "entry-1", title: "GigaChat" }];
  tab.hass = net.hass;
  await flush();
  const editor = tab.querySelector(".sc-tools-editor:not(.sc-tools-export)");
  return { net, tab, editor };
}

/** What the user typed, delivered the way a textarea delivers it. */
function type(editor, text) {
  editor.value = text;
  editor.dispatchEvent(new Event("input"));
}

let confirmSpy;

beforeEach(() => {
  // jsdom has no real dialogs; each test states outright what the user answered.
  confirmSpy = vi.fn(() => false);
  globalThis.confirm = confirmSpy;
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("sc-tools-tab: the editor loads and Save tracks the baseline", () => {
  it("shows the file the backend served and keeps Save disabled until it differs", async () => {
    const { tab, editor } = await boot();
    expect(editor.value).toBe(ON_DISK);
    expect(tab.querySelector("#sc-tools-save").hasAttribute("disabled")).toBe(true);

    type(editor, `${ON_DISK}  - name: added\n`);
    expect(tab.querySelector("#sc-tools-save").hasAttribute("disabled")).toBe(false);

    // Typed back to exactly what was loaded: there is nothing to save again.
    type(editor, ON_DISK);
    expect(tab.querySelector("#sc-tools-save").hasAttribute("disabled")).toBe(true);
  });
});

describe("sc-tools-tab: base_hash", () => {
  it("sends the hash that came with the text the editor is based on", async () => {
    // The concurrency guarantee in one assertion: the backend can only refuse
    // a stale write if the panel actually tells it which version it read.
    const { net, tab, editor } = await boot({
      "smartchain/tools/save": { ok: true, hash: "hash-after-save" },
    });
    type(editor, "tools: []\n");
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/tools/save")).toEqual([
      { type: "smartchain/tools/save", text: "tools: []\n", base_hash: DISK_HASH },
    ]);
  });

  it("adopts the hash the save returned, so a second save is not self-stale", async () => {
    const { net, tab, editor } = await boot({
      "smartchain/tools/save": { ok: true, hash: "hash-after-save" },
    });
    type(editor, "tools: []\n");
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    type(editor, "tools: []\n# again\n");
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    const saves = net.calls("smartchain/tools/save");
    expect(saves).toHaveLength(2);
    expect(saves[1].base_hash).toBe("hash-after-save");
  });

  it("sends null for a file that does not exist yet", async () => {
    const { net, tab, editor } = await boot({
      "smartchain/tools/get": {
        path: "/config/smartchain/tools.yaml",
        text: "",
        exists: false,
        error: null,
        hash: null,
        backup_exists: false,
      },
      "smartchain/tools/save": { ok: true, hash: "hash-of-the-new-file" },
    });
    type(editor, "tools: []\n");
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/tools/save")[0].base_hash).toBeNull();
  });
});

describe("sc-tools-tab: a stale refusal never silently overwrites the editor", () => {
  const MINE = "tools:\n  - name: mine_unsaved\n";
  const stale = { "smartchain/tools/save": { ok: false, reason: "stale" } };

  it("leaves the user's text alone when they decline the reload", async () => {
    confirmSpy.mockReturnValue(false);
    const { net, tab, editor } = await boot(stale);
    type(editor, MINE);
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    // The offer has to say what accepting costs — a reload that quietly ate an
    // unsaved edit is the failure this whole path exists to prevent.
    expect(confirmSpy.mock.calls[0][0]).toMatch(/DISCARDS/);
    expect(editor.value).toBe(MINE);
    // Declining must not re-read the file either: one boot-time get, no more.
    expect(net.calls("smartchain/tools/get")).toHaveLength(1);
    // And the edit is still savable — the tab is usable after the refusal.
    expect(tab.querySelector("#sc-tools-save").hasAttribute("disabled")).toBe(false);
  });

  it("replaces the text only after the user accepts, and rebases on the new hash", async () => {
    confirmSpy.mockReturnValue(true);
    const changed = "tools:\n  - name: changed_by_ssh\n";
    const { net, tab, editor } = await boot({
      ...stale,
      "smartchain/tools/get": {
        path: "/config/smartchain/tools.yaml",
        text: changed,
        exists: true,
        error: null,
        hash: "hash-after-ssh",
        backup_exists: true,
      },
    });
    type(editor, MINE);
    tab.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/tools/get")).toHaveLength(2);
    expect(editor.value).toBe(changed);
    expect(tab._baseHash).toBe("hash-after-ssh");
  });

  it("keeps the text after every other refusal reason too", async () => {
    for (const result of [
      { ok: false, reason: "invalid", error: "line 3: bad" },
      { ok: false, reason: "write_failed", error: "permission denied" },
      { ok: false, reason: "reload_failed", error: "boom" },
      { ok: false, reason: "something_new" },
    ]) {
      const { editor } = await boot({ "smartchain/tools/save": result });
      type(editor, MINE);
      document.querySelector("#sc-tools-save").dispatchEvent(new Event("click"));
      await flush();
      expect(editor.value, `reason=${result.reason}`).toBe(MINE);
      document.body.innerHTML = "";
    }
    // None of them asked to discard anything.
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

describe("sc-tools-tab: a hass tick is not a repaint", () => {
  it("survives twenty state pushes with the same node and the same text", async () => {
    const { net, tab, editor } = await boot();
    type(editor, "tools:\n  - name: half_typed\n");

    for (let i = 0; i < 20; i += 1) tab.hass = { ...net.hass };
    await flush();

    expect(tab.querySelector(".sc-tools-editor:not(.sc-tools-export)")).toBe(editor);
    expect(editor.value).toBe("tools:\n  - name: half_typed\n");
    expect(net.calls("smartchain/tools/get")).toHaveLength(1);
  });

  it("does not repaint the tool list out from under an open tool form", async () => {
    const { tab } = await boot();
    tab._editing = { entryId: "entry-1", subentryId: null };
    tab._paintList();
    expect(tab.querySelector("sc-config-form")).not.toBeNull();

    // A refetched overview array is a new object, so `set entries` would
    // normally repaint — and would destroy the half-filled form.
    tab.entries = [{ entry_id: "entry-1", title: "GigaChat" }];
    expect(tab.querySelector("sc-config-form")).not.toBeNull();
  });
});
