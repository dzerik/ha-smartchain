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

/**
 * The answer <sc-config-form> gets when a tool form opens. Nothing in these
 * tests reads the field — it only has to be a schema the form can render, so
 * that "the form is open" is a real form and not a stub.
 */
const FORM_SCHEMA = {
  "smartchain/tool/schema": {
    schema: [{ name: "name", selector: { text: {} } }],
    data: { name: "" },
    labels: {},
  },
};

/** Open the tool form the way the "+ Tool" button does, and let it load. */
async function openForm(tab) {
  tab._editing = { entryId: "entry-1", subentryId: null };
  tab._paintList();
  await flush();
  const form = tab.querySelector("sc-config-form");
  expect(form).not.toBeNull();
  return form;
}

/**
 * A keystroke in the form, delivered the way <ha-form> delivers one — which is
 * also the only place the half-typed value lives, since nothing writes it back
 * to the DOM until the next `_apply()`.
 */
function typeIntoForm(form, value) {
  form
    .querySelector("ha-form")
    .dispatchEvent(new CustomEvent("value-changed", { detail: { value } }));
  expect(form._data).toEqual(value);
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
    const { tab } = await boot(FORM_SCHEMA);
    const form = await openForm(tab);
    typeIntoForm(form, { name: "half_typed_tool" });

    // A refetched overview array is a new object, so `set entries` would
    // normally repaint — and would destroy the half-filled form.
    tab.entries = [{ entry_id: "entry-1", title: "GigaChat" }];

    // `not.toBeNull()` would pass on a *replacement* form: repainting writes a
    // fresh <sc-config-form> into the same container, so the query finds one
    // either way. Only node identity distinguishes "still open" from "silently
    // started over", which is the whole guarantee this test is named for.
    const live = tab.querySelector("sc-config-form");
    expect(live).toBe(form);
    expect(form.isConnected).toBe(true);
    expect(live.querySelector("ha-form")).toBe(form.querySelector("ha-form"));
    // And what the user typed is still in it, not reset to the loaded defaults.
    expect(live._data).toEqual({ name: "half_typed_tool" });
  });

  it("does not repaint when a tool-list refresh lands while a form is open", async () => {
    // The same guarantee on the other path, and a race that really happens:
    // `_loadList` is two awaited websocket calls long, so the user can open the
    // form before its answer arrives. Without the guard, the answer's repaint
    // destroys the form that was opened in the meantime.
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const net = fakeHass(
      handlers({
        ...FORM_SCHEMA,
        "smartchain/tool/list": () => gate.then(() => ({ tools: [], shadowed_yaml: [] })),
      })
    );
    const tab = mount("sc-tools-tab");
    tab.entries = [{ entry_id: "entry-1", title: "GigaChat" }];
    tab.hass = net.hass;
    await flush();

    const form = await openForm(tab);
    typeIntoForm(form, { name: "typed_while_loading" });

    release();
    await flush();

    expect(tab.querySelector("sc-config-form")).toBe(form);
    expect(form.isConnected).toBe(true);
    expect(form._data).toEqual({ name: "typed_while_loading" });
  });

  it("ignores an entries push that is the same array it already holds", async () => {
    // Home Assistant's shell re-pushes `.entries` whenever it (re)mounts a tab;
    // only a genuine refetch produces a new array. Repainting on the identical
    // object would throw the rendered list away for nothing — and, before the
    // form guard above existed, was exactly how an open form got destroyed.
    const { tab } = await boot();
    const entries = [{ entry_id: "entry-1", title: "GigaChat" }];
    tab.entries = entries;
    const section = tab.querySelector(".sc-tools-constructor .sc-entry");
    expect(section).not.toBeNull();

    tab.entries = entries;
    expect(tab.querySelector(".sc-tools-constructor .sc-entry")).toBe(section);

    // ...and a refetched array must still repaint, or the guard has gone from
    // "skip the redundant push" to "never update".
    tab.entries = [...entries];
    expect(tab.querySelector(".sc-tools-constructor .sc-entry")).not.toBe(section);
  });
});
