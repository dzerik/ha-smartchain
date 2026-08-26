import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../components/config-form.js";
import { fakeHass, flush, mount } from "./harness.js";

/**
 * Every toast currently on screen, newest last. `showToast` appends into a
 * container on `document.body`, so this reads the real thing rather than a
 * mock — the point of these tests is that the user is *told*, and a spy on the
 * function would still pass if the call never reached the DOM.
 */
function toasts() {
  return [...document.querySelectorAll(".sc-toast")].map((el) => el.textContent.trim());
}

/** True when some toast on screen carries `text`. Substring, not equality: a
 * toast may also hold chrome of its own (a dismiss control, an icon), which is
 * `showToast`'s business and not what these tests are about. */
function toasted(text) {
  return toasts().some((shown) => shown.includes(text));
}

/** A form instance with a schema attached, without going near the network. */
function formWithSchema(names) {
  const form = document.createElement("sc-config-form");
  form._schema = names.map((name) => ({ name, selector: { text: {} } }));
  return form;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

/**
 * `_parseError` is the panel's half of the `invalid_data` protocol. The other
 * half is `websocket_api.invalid_data()`, and the strings below were produced
 * by calling that function — not written from memory — because the whole point
 * of the protocol is that the two ends agree. When they disagree the failure
 * is silent: the message is toasted whole instead of being attached to the
 * field, and the user reads a machine key.
 */
describe("ScConfigForm._parseError", () => {
  it("splits the field list from the human reason", () => {
    const form = formWithSchema(["model", "prompt"]);
    expect(
      form._parseError(
        "invalid_data: model — Select a model from the list, or type a custom model name."
      )
    ).toEqual({
      fields: ["model"],
      text: "Select a model from the list, or type a custom model name.",
    });
  });

  it("reads a multi-field message the way the backend joins one", () => {
    const form = formWithSchema(["base_url", "model"]);
    // `invalid_data(["base_url", "model"])` — sorted, ", "-joined, no reason.
    expect(form._parseError("invalid_data: base_url, model")).toEqual({
      fields: ["base_url", "model"],
      text: null,
    });
  });

  it("keeps commas inside the reason, because the em dash is the separator", () => {
    // This is exactly why `invalid_data()` uses an em dash: a field name can
    // never contain one, so a reason full of commas — or of further em dashes
    // — still survives the split intact.
    const form = formWithSchema(["model"]);
    expect(form._parseError("invalid_data: model — one, two, three — all wrong")).toEqual({
      fields: ["model"],
      text: "one, two, three — all wrong",
    });
  });

  it("carries a reason that names no field", () => {
    // `invalid_data([], detail)` — the degraded form, for a failure with no
    // identifiable field. It has to be toasted, so the text must survive even
    // though there is nothing to attach it to.
    const form = formWithSchema(["name"]);
    expect(
      form._parseError("invalid_data — Home Assistant could not store this value.")
    ).toEqual({
      fields: [],
      text: "Home Assistant could not store this value.",
    });
  });

  it("handles the bare code older commands still send", () => {
    const form = formWithSchema(["name"]);
    expect(form._parseError("invalid_data")).toEqual({ fields: [], text: null });
  });

  it("drops a named field this schema does not declare", () => {
    // A field the form is not showing cannot be highlighted, so it must not be
    // reported as one — otherwise `save()` sets `_fieldErrors` on a key
    // <ha-form> ignores and the user sees no error at all.
    const form = formWithSchema(["name"]);
    expect(form._parseError("invalid_data: name, secret_key — nope")).toEqual({
      fields: ["name"],
      text: "nope",
    });
  });

  it("does not claim a field before the schema has arrived", () => {
    const form = document.createElement("sc-config-form");
    expect(form._schema).toBeNull();
    expect(form._parseError("invalid_data: model — nope")).toEqual({
      fields: [],
      text: "nope",
    });
  });

  it("treats a message that is not the protocol as no protocol at all", () => {
    const form = formWithSchema(["model"]);
    expect(form._parseError("Connection lost")).toEqual({ fields: [], text: null });
    expect(form._parseError("")).toEqual({ fields: [], text: null });
  });
});

/**
 * `_merged` decides who wins when a schema response lands on a form the user
 * has been typing into. Getting it backwards is the difference between
 * "Refresh models" costing a dropdown and it costing a hand-written prompt.
 */
describe("ScConfigForm._merged", () => {
  it("lets the server win on an automatic or reactive load", () => {
    const form = document.createElement("sc-config-form");
    form._data = { prompt: "typed by the user" };
    const result = {
      data: { prompt: "stored on the server", model: "gpt-4o" },
      schema: [{ name: "prompt" }, { name: "model" }],
    };
    expect(form._merged(result, false)).toEqual({
      prompt: "stored on the server",
      model: "gpt-4o",
    });
  });

  it("keeps the user's edits on a refresh", () => {
    const form = document.createElement("sc-config-form");
    form._data = { prompt: "typed by the user", model: "" };
    const result = {
      data: { prompt: "stored on the server", model: "gpt-4o" },
      schema: [{ name: "prompt" }, { name: "model" }],
    };
    // Both fields are declared, so both of the user's values stand — including
    // the empty model they were about to pick from the refreshed list.
    expect(form._merged(result, true)).toEqual({ prompt: "typed by the user", model: "" });
  });

  it("drops an edit to a field the refreshed schema no longer declares", () => {
    // Putting a pruned key back would have the next save rejected as an extra
    // key, so a conditional field that has gone out of schema stays gone.
    const form = document.createElement("sc-config-form");
    form._data = { prompt: "typed", collection: "left over from qdrant" };
    const result = { data: { prompt: "served" }, schema: [{ name: "prompt" }] };
    expect(form._merged(result, true)).toEqual({ prompt: "typed" });
  });

  it("survives a response with neither data nor schema", () => {
    const form = document.createElement("sc-config-form");
    form._data = { prompt: "typed" };
    expect(form._merged({}, false)).toEqual({});
    expect(form._merged({}, true)).toEqual({});
  });
});

/**
 * The blank-form bug. `root.innerHTML = "<sc-config-form></sc-config-form>"`
 * connects the element synchronously, so `connectedCallback` runs *before* the
 * host has finished setting `.hass` / `.commands` / `.entryId` on the lines
 * that follow. A load started then would no-op and never be retried, and the
 * form would sit empty forever. Home Assistant then pushes `.hass` on every
 * state change in the house, so the same readiness check must not turn that
 * into a load per tick.
 */
describe("ScConfigForm load readiness", () => {
  let net;

  beforeEach(() => {
    net = fakeHass({
      "smartchain/agent/schema": {
        schema: [{ name: "prompt", selector: { text: {} } }],
        data: { prompt: "hello" },
        labels: { prompt: "Prompt" },
      },
    });
  });

  it("does not load until all three of hass, commands and entryId have arrived", async () => {
    const form = mount("sc-config-form");
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(0);

    form.hass = net.hass;
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(0);

    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(0);

    form.entryId = "entry-1";
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(1);
    expect(net.calls("smartchain/agent/schema")[0]).toMatchObject({
      entry_id: "entry-1",
      refresh: false,
    });
    expect(form._data).toEqual({ prompt: "hello" });
  });

  it("loads whichever property completes the set last", async () => {
    // The host sets them in a different order — entryId first, hass last,
    // which is what happens when a tab is painted before HA's first tick.
    const form = mount("sc-config-form");
    form.entryId = "entry-1";
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(0);

    form.hass = net.hass;
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(1);
  });

  it("loads once, no matter how many times Home Assistant pushes hass", async () => {
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(1);

    for (let i = 0; i < 20; i += 1) form.hass = { ...net.hass };
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(1);
  });

  it("loads a form whose properties were all set before it was connected", async () => {
    // The mirror image of the blank-form bug. A host that builds the element
    // detached — createElement, set everything, then append — touches no setter
    // after connection, so connectedCallback is the only thing left that can
    // start the load. Nothing may load before then either: `_render()` runs
    // there too, so a load started earlier would have no <ha-form> to fill.
    const form = document.createElement("sc-config-form");
    form.hass = net.hass;
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(0);

    document.body.appendChild(form);
    await flush();
    expect(net.calls("smartchain/agent/schema")).toHaveLength(1);
    expect(form._data).toEqual({ prompt: "hello" });
  });

  it("still lets Refresh reload explicitly after the automatic load is spent", async () => {
    // `_loaded` gates the *automatic* load only. If it gated `load()` itself,
    // the Refresh button would go dead after the form first appeared.
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();

    form.querySelector("#sc-form-refresh").dispatchEvent(new Event("click"));
    await flush();

    const calls = net.calls("smartchain/agent/schema");
    expect(calls).toHaveLength(2);
    expect(calls[1].refresh).toBe(true);
  });
});

/**
 * A schema command that fails on the *first* load used to leave the form dead:
 * `_apply()` returns early with no schema, so nothing renders at all, and
 * "Refresh models" — the only control that calls `load()` again — is hidden on
 * the store, tool and settings forms. A toast that has faded is then the whole
 * record of what happened, and the user is looking at a blank rectangle with a
 * Save button.
 */
describe("ScConfigForm: a failed first load has a way out", () => {
  const COMMANDS = { schema: "smartchain/store/schema", save: "smartchain/store/save" };
  const GOOD = {
    schema: [{ name: "name", selector: { text: {} } }],
    data: { name: "home_notes" },
    labels: { name: "Name" },
  };

  /** A schema command that throws `attempts` times, then succeeds. */
  function flaky(attempts, message) {
    let seen = 0;
    return () => {
      seen += 1;
      if (seen <= attempts) throw new Error(message);
      return GOOD;
    };
  }

  async function mountFailing(message, attempts = 1) {
    const net = fakeHass({ "smartchain/store/schema": flaky(attempts, message) });
    const form = mount("sc-config-form");
    // Refresh is hidden exactly as the stores tab hides it — the state where
    // there was no way back at all.
    form.showRefresh = false;
    form.commands = COMMANDS;
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    return { net, form };
  }

  it("says what happened and what to do, instead of rendering nothing", async () => {
    const { form } = await mountFailing("Connection lost");

    const box = form.querySelector(".sc-form-error");
    expect(box).not.toBeNull();
    expect(box.classList.contains("sc-hidden")).toBe(false);
    // What happened: the backend's own words, not a generic apology.
    expect(box.textContent).toContain("Connection lost");
    // What to do: a control that is actually there, named in the text.
    expect(box.textContent).toMatch(/Retry/);
    expect(form.querySelector("#sc-form-retry")).not.toBeNull();
    // And the failure is still loud in the moment, not swapped for the banner.
    expect(toasted("Connection lost")).toBe(true);
  });

  it("retries the load from that state and comes back to a working form", async () => {
    const { net, form } = await mountFailing("Connection lost");
    expect(net.calls("smartchain/store/schema")).toHaveLength(1);

    form.querySelector("#sc-form-retry").dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/store/schema")).toHaveLength(2);
    expect(form._data).toEqual({ name: "home_notes" });
    expect(form.querySelector("ha-form").schema).toEqual(GOOD.schema);
    const box = form.querySelector(".sc-form-error");
    expect(box.classList.contains("sc-hidden")).toBe(true);
  });

  it("shows the error again if the retry fails too", async () => {
    const { net, form } = await mountFailing("Connection lost", 2);
    form.querySelector("#sc-form-retry").dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/store/schema")).toHaveLength(2);
    const box = form.querySelector(".sc-form-error");
    expect(box.classList.contains("sc-hidden")).toBe(false);
    expect(box.textContent).toContain("Connection lost");
  });

  it("does not blank a loaded form when a later refresh fails", async () => {
    // The other half of the guarantee, and the reason the error state is
    // conditional: a failed "Refresh models" must leave the form — and the
    // half-typed values in it — exactly as they were.
    let calls = 0;
    const net = fakeHass({
      "smartchain/agent/schema": () => {
        calls += 1;
        if (calls === 1) return GOOD;
        throw new Error("Connection lost");
      },
    });
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    form
      .querySelector("ha-form")
      .dispatchEvent(new CustomEvent("value-changed", { detail: { value: { name: "typed" } } }));

    form.querySelector("#sc-form-refresh").dispatchEvent(new Event("click"));
    await flush();

    expect(form._data).toEqual({ name: "typed" });
    expect(form.querySelector("ha-form").schema).toEqual(GOOD.schema);
    expect(form.querySelector(".sc-form-error").classList.contains("sc-hidden")).toBe(true);
    expect(toasted("Connection lost")).toBe(true);
  });
});

/**
 * A rejected Save used to attach the reason to the field and say nothing else.
 * On a long form — an agent has a prompt box tall enough to fill the screen —
 * the field is usually off-screen, so what the user sees is a Save button that
 * did nothing at all. The error must be audible where the user is looking, and
 * the form must move to the field it is about.
 */
describe("ScConfigForm: a refused Save is never silent", () => {
  const SCHEMA = {
    schema: [
      { name: "model", selector: { text: {} } },
      { name: "prompt", selector: { text: {} } },
    ],
    data: { model: "", prompt: "you are a helpful assistant" },
    labels: { model: "Model", prompt: "Prompt" },
  };

  async function boot(saveAnswer) {
    const net = fakeHass({
      "smartchain/agent/schema": SCHEMA,
      "smartchain/agent/save": saveAnswer,
    });
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    // jsdom implements no scrolling at all, so the call has to be observed
    // rather than its effect.
    const scrolled = vi.fn();
    form.querySelector("ha-form").scrollIntoView = scrolled;
    return { net, form, scrolled };
  }

  async function clickSave(form) {
    form.querySelector("#sc-form-save").dispatchEvent(new Event("click"));
    await flush();
  }

  it("toasts the field and the reason, and scrolls the form to it", async () => {
    const { form, scrolled } = await boot(() => {
      throw new Error(
        "invalid_data: model — Select a model from the list, or type a custom model name."
      );
    });
    await clickSave(form);

    // The field still carries the error — that part was already right.
    expect(form._fieldErrors).toEqual({
      model: "Select a model from the list, or type a custom model name.",
    });
    // ...and now the user is told, in the label they see on the field, not the
    // machine name the backend used.
    const shown = toasts().join(" | ");
    expect(shown).toContain("Model");
    expect(shown).toContain("Select a model from the list");
    expect(scrolled).toHaveBeenCalledTimes(1);
  });

  it("names every rejected field, not just the first", async () => {
    const { form } = await boot(() => {
      throw new Error("invalid_data: model, prompt — Fill both of these in.");
    });
    await clickSave(form);

    const shown = toasts().join(" | ");
    expect(shown).toContain("Model");
    expect(shown).toContain("Prompt");
  });

  it("still toasts a refusal that names no field at all", async () => {
    const { form, scrolled } = await boot(() => {
      throw new Error("Connection lost");
    });
    await clickSave(form);

    expect(form._fieldErrors).toBeNull();
    expect(toasted("Connection lost")).toBe(true);
    // Nothing to scroll to: no field was named.
    expect(scrolled).not.toHaveBeenCalled();
  });

  it("says nothing and scrolls nowhere when the save succeeds", async () => {
    const { form, scrolled } = await boot({ ok: true });
    await clickSave(form);

    expect(toasted("Saved")).toBe(true);
    expect(toasts().join(" | ")).not.toContain("Not saved");
    expect(scrolled).not.toHaveBeenCalled();
  });
});

/**
 * Save is one websocket round trip away from creating a config subentry, and
 * nothing used to stop a second click starting a second one. On the agents tab
 * that is two agents from one form — the duplicate has to be found and deleted
 * by hand, and it is indistinguishable from the real one.
 *
 * The unit under test is the number of calls that reach the backend, not the
 * presence of a flag: a flag that is set and never consulted would satisfy any
 * test written against the flag itself.
 */
describe("ScConfigForm: Save cannot be double-submitted", () => {
  const SCHEMA = {
    "smartchain/agent/schema": {
      schema: [{ name: "name", selector: { text: {} } }],
      data: { name: "Kitchen" },
      labels: { name: "Name" },
    },
  };

  /** A form whose save command hangs until the returned `release` is called. */
  async function bootGated(answer = { ok: true }) {
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const net = fakeHass({
      ...SCHEMA,
      "smartchain/agent/save": () => gate.then(() => answer),
    });
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    return { net, form, release, button: form.querySelector("#sc-form-save") };
  }

  it("sends one save for two clicks in the same tick", async () => {
    const { net, form, release, button } = await bootGated();

    button.dispatchEvent(new Event("click"));
    button.dispatchEvent(new Event("click"));
    await flush();

    expect(net.calls("smartchain/agent/save")).toHaveLength(1);

    // And the button says so while it is in flight, rather than looking idle.
    expect(button.disabled).toBe(true);

    release();
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(1);
  });

  it("does not go dead: a later click still saves", async () => {
    // The guard must be a flight, not a fuse. A form that is not unmounted on
    // save — and after a *failed* save nothing unmounts it — has to stay usable.
    const { net, form, release, button } = await bootGated();
    button.dispatchEvent(new Event("click"));
    await flush();
    release();
    await flush();
    expect(button.disabled).toBe(false);

    button.dispatchEvent(new Event("click"));
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(2);
  });

  it("releases the guard when the save fails", async () => {
    const net = fakeHass({
      ...SCHEMA,
      "smartchain/agent/save": () => {
        throw new Error("Connection lost");
      },
    });
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();

    const button = form.querySelector("#sc-form-save");
    button.dispatchEvent(new Event("click"));
    await flush();
    expect(toasted("Connection lost")).toBe(true);
    expect(button.disabled).toBe(false);

    button.dispatchEvent(new Event("click"));
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(2);
  });

  it("fires sc-before-save once for two clicks", async () => {
    // A host may answer `sc-before-save` with a dialog of its own — the rename
    // confirmation does. Counting only the websocket calls would let a second
    // click still put a second dialog on screen.
    const { form, release, button } = await bootGated();
    const before = vi.fn();
    form.addEventListener("sc-before-save", before);

    button.dispatchEvent(new Event("click"));
    button.dispatchEvent(new Event("click"));
    await flush();

    expect(before).toHaveBeenCalledTimes(1);
    release();
    await flush();
  });

  it("guards the public save() too, not only the button", async () => {
    // `save()` is public: a host that intercepted `sc-before-save` drives it
    // itself, and nothing stops that host — or a stray second confirmation —
    // from calling it twice. The button guard cannot see any of that.
    const { net, form, release } = await bootGated();

    form.save();
    form.save();
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(1);

    release();
    await flush();
  });

  it("still lets a host that intercepted sc-before-save call save() itself", async () => {
    // The rename-confirmation path: the host preventDefaults, satisfies itself,
    // then calls `form.save()`. The guard must not have swallowed that.
    const { net, form, release } = await bootGated();
    form.addEventListener("sc-before-save", (ev) => ev.preventDefault());

    form.querySelector("#sc-form-save").dispatchEvent(new Event("click"));
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(0);

    form.save();
    await flush();
    expect(net.calls("smartchain/agent/save")).toHaveLength(1);
    release();
    await flush();
  });
});

/**
 * `hasUnsavedChanges` is what the shell asks before it throws a tab's DOM away.
 * It has to be true for exactly as long as there is something to lose:
 * pessimistic enough that no edit is discarded without a question, and quiet
 * enough that a form nobody touched never produces one — a confirmation the
 * user learns to dismiss protects nothing.
 */
describe("ScConfigForm.hasUnsavedChanges", () => {
  const SCHEMA = {
    "smartchain/agent/schema": {
      schema: [{ name: "prompt", selector: { text: {} } }],
      data: { prompt: "hello" },
      labels: { prompt: "Prompt" },
    },
  };

  async function boot(extra = {}) {
    const net = fakeHass({ ...SCHEMA, ...extra });
    const form = mount("sc-config-form");
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    return { net, form };
  }

  function type(form, value) {
    form
      .querySelector("ha-form")
      .dispatchEvent(new CustomEvent("value-changed", { detail: { value } }));
  }

  it("is false on a form nobody has touched", async () => {
    const { form } = await boot();
    expect(form.hasUnsavedChanges).toBe(false);
  });

  it("is false before anything has loaded at all", async () => {
    const form = mount("sc-config-form");
    expect(form.hasUnsavedChanges).toBe(false);
  });

  it("becomes true the moment a field changes", async () => {
    const { form } = await boot();
    type(form, { prompt: "hello, and something else" });
    expect(form.hasUnsavedChanges).toBe(true);
  });

  it("ignores a value-changed that changes nothing", async () => {
    // <ha-form> re-emits on focus changes and on our own `form.data =`
    // assignment. Treating those as edits would put a confirmation in front of
    // a user who only opened a form and switched tabs again.
    const { form } = await boot();
    type(form, { prompt: "hello" });
    expect(form.hasUnsavedChanges).toBe(false);
  });

  it("is false again after a successful save", async () => {
    const { form } = await boot({ "smartchain/agent/save": { ok: true } });
    type(form, { prompt: "changed" });
    expect(form.hasUnsavedChanges).toBe(true);

    form.querySelector("#sc-form-save").dispatchEvent(new Event("click"));
    await flush();
    expect(form.hasUnsavedChanges).toBe(false);
  });

  it("stays true when the save was refused", async () => {
    // The edit is still only in this form — that is precisely when losing it
    // to a tab click would hurt most.
    const { form } = await boot({
      "smartchain/agent/save": () => {
        throw new Error("invalid_data: prompt — Too long.");
      },
    });
    type(form, { prompt: "changed" });
    form.querySelector("#sc-form-save").dispatchEvent(new Event("click"));
    await flush();
    expect(form.hasUnsavedChanges).toBe(true);
  });

  it("survives Refresh models, which keeps the edits it was pressed for", async () => {
    const { form } = await boot();
    type(form, { prompt: "half typed" });
    form.querySelector("#sc-form-refresh").dispatchEvent(new Event("click"));
    await flush();
    expect(form._data).toEqual({ prompt: "half typed" });
    expect(form.hasUnsavedChanges).toBe(true);
  });

  it("is not disturbed by Home Assistant's state ticks", async () => {
    const { net, form } = await boot();
    for (let i = 0; i < 20; i += 1) form.hass = { ...net.hass };
    await flush();
    expect(form.hasUnsavedChanges).toBe(false);
  });
});

/**
 * <ha-form> answers a `data` assignment with a `value-changed` of its own, and
 * the value it sends back is not always identical: it fills in defaults for
 * keys the schema declares but the payload had no value for. That is this
 * component talking to itself, not a user typing.
 *
 * The guard used to be a synchronous `_applying` flag around the assignment,
 * which is only correct if <ha-form> echoes inside the assignment. Nothing
 * promises that — a selector that settles its own value one frame later echoes
 * a frame later — and when it does not, every form is dirty the moment it
 * loads: a "you have unsaved changes" question on every tab switch after
 * merely opening a form, which is exactly the confirmation users learn to
 * click through without reading.
 *
 * So the echo is recognised by what the value *is* — every key we handed over
 * still carrying the value we handed over — and not by when it arrives.
 */
describe("ScConfigForm: an <ha-form> that echoes the data we hand it", () => {
  const SCHEMA = {
    "smartchain/agent/schema": {
      schema: [{ name: "prompt", selector: { text: {} } }],
      data: { prompt: "hello" },
      labels: { prompt: "Prompt" },
    },
  };

  /**
   * Make `haForm` behave like Home Assistant's: every `data` assignment comes
   * back as a value-changed carrying a normalised copy — one extra key the
   * schema declares a default for. `when` decides only the timing.
   */
  function echoing(haForm, when) {
    let stored;
    Object.defineProperty(haForm, "data", {
      configurable: true,
      get: () => stored,
      set(value) {
        stored = value;
        const echo = () =>
          haForm.dispatchEvent(
            new CustomEvent("value-changed", { detail: { value: { ...value, extra: "default" } } })
          );
        if (when === "sync") echo();
        else setTimeout(echo, 0);
      },
    });
  }

  async function boot(when, extra = {}) {
    const net = fakeHass({ ...SCHEMA, ...extra });
    const form = mount("sc-config-form");
    // Before the load, so the very first `_apply` is echoed too — the moment
    // the async version used to turn a freshly opened form dirty.
    echoing(form.querySelector("ha-form"), when);
    form.commands = { schema: "smartchain/agent/schema", save: "smartchain/agent/save" };
    form.entryId = "entry-1";
    form.hass = net.hass;
    await flush();
    return { net, form };
  }

  for (const when of ["sync", "async"]) {
    it(`leaves a freshly loaded form clean when the echo is ${when}`, async () => {
      const { form } = await boot(when);
      expect(form._data).toEqual({ prompt: "hello", extra: "default" });
      expect(form.hasUnsavedChanges).toBe(false);
    });

    it(`leaves a just-saved form clean when the echo is ${when}`, async () => {
      const { form } = await boot(when, { "smartchain/agent/save": { ok: true } });
      form
        .querySelector("ha-form")
        .dispatchEvent(new CustomEvent("value-changed", { detail: { value: { prompt: "typed" } } }));
      expect(form.hasUnsavedChanges).toBe(true);

      form.querySelector("#sc-form-save").dispatchEvent(new Event("click"));
      await flush();

      expect(form.hasUnsavedChanges).toBe(false);
    });

    it(`still sees a real edit as one when the echo is ${when}`, async () => {
      // The exemption is for values we handed over coming back unchanged, not
      // for "anything that arrives soon after a load". An emission that
      // rewrites one of them is an edit however early it lands.
      const { form } = await boot(when);
      form.querySelector("ha-form").dispatchEvent(
        new CustomEvent("value-changed", {
          detail: { value: { prompt: "typed over it", extra: "default" } },
        })
      );
      expect(form.hasUnsavedChanges).toBe(true);
    });
  }

  it("does not lose a dirty flag to an echo that lands after the edit", async () => {
    // The orders can interleave: the user types before a slow selector has
    // finished settling. The late echo must not talk the form back to clean.
    const { form } = await boot("async");
    const haForm = form.querySelector("ha-form");
    haForm.dispatchEvent(
      new CustomEvent("value-changed", { detail: { value: { prompt: "typed", extra: "default" } } })
    );
    expect(form.hasUnsavedChanges).toBe(true);

    haForm.dispatchEvent(
      new CustomEvent("value-changed", { detail: { value: { prompt: "typed", extra: "default" } } })
    );
    await flush();
    expect(form.hasUnsavedChanges).toBe(true);
  });
});
