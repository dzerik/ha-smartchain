import { afterEach, beforeEach, describe, expect, it } from "vitest";

import "../components/config-form.js";
import { fakeHass, flush, mount } from "./harness.js";

/** A form instance with a schema attached, without going near the network. */
function formWithSchema(names) {
  const form = document.createElement("sc-config-form");
  form._schema = names.map((name) => ({ name, selector: { text: {} } }));
  return form;
}

afterEach(() => {
  document.body.innerHTML = "";
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
