import { callWS, escapeHtml, showToast } from "../services.js";
// Same cache-busting query this module was loaded with — importing
// config-form.js both with and without `?v=` would instantiate it twice and
// the second customElements.define would throw.
const _v = new URL(import.meta.url).searchParams.get("v") || "";
await import(`./config-form.js${_v ? `?v=${_v}` : ""}`);

const TOOL_COMMANDS = {
  schema: "smartchain/tool/schema",
  save: "smartchain/tool/save",
};

/**
 * Shown via the `<textarea>`'s `placeholder` attribute — native browser
 * behaviour, not a value: it renders only while the field is empty, is never
 * part of `.value`, and disappears the moment the user types a single
 * character. It can therefore never end up on disk, accidentally or
 * otherwise — Save stays disabled until the textarea differs from the loaded
 * baseline, and an untouched empty editor has nothing to save.
 */
const TOOLS_PLACEHOLDER = `# tools.yaml — the file form of what the constructor above builds.
# You do not need this file: tools built above are stored by Home Assistant.
# It stays supported for tools written before the constructor existed, for
# mcp_servers:, and for memory: stores. See "Syntax reference" below.
#
# tools:
#   - name: turn_on_porch_light
#     description: Turn on the porch light.
#     parameters:
#       type: object
#       properties: {}
#     action:
#       type: service
#       domain: light
#       service: turn_on
#       target:
#         entity_id: light.porch`;

/**
 * Static reference markup for the collapsed <details> help panel. Every
 * example here was checked against tools/schema.py and the executors in
 * tools/actions/ — not written from memory — so keep it that way when this
 * drifts: a syntax reference that disagrees with the validator is worse than
 * no reference at all, because the user cannot tell which one is wrong.
 *
 * Entirely static, authored text — never interpolates file content or any
 * other runtime value, so it does not need escapeHtml().
 */
const TOOLS_HELP_HTML = `
  <details class="sc-tools-help">
    <summary>Syntax reference — tools.yaml</summary>
    <div class="sc-tools-help-body">

      <section>
        <h4>Top-level blocks</h4>
        <p>All three are optional; a file with none of them is valid (and empty).</p>
        <pre><code>tools:         # custom LLM tools — also buildable above, without YAML
mcp_servers:   # remote MCP servers; their tools are added automatically
memory:        # long-term memory and/or entity indexing</code></pre>
      </section>

      <section>
        <h4>A tool</h4>
        <p>Every entry under <code>tools:</code> needs <code>name</code>, <code>description</code>,
        <code>parameters</code> (a JSON Schema <code>object</code> describing the call's arguments)
        and <code>action</code>. <code>name</code> is lowercase letters, digits and underscores,
        starting with a letter or underscore — and can't be one of the six built-in tool names:
        <code>get_state_history</code>, <code>ask_agent</code>, <code>ask_agents</code>,
        <code>critique_response</code>, <code>search_memory</code> or <code>search_entities</code>.
        There are four action types you write by hand: <code>service</code>, <code>template</code>,
        <code>rest</code>, <code>script</code> — plus <code>mcp</code>, which is never hand-written
        (see below).</p>
      </section>

      <section>
        <h4><code>service</code> — call a Home Assistant service</h4>
        <pre><code>- name: turn_on_porch_light
  description: Turn on the porch light.
  parameters:
    type: object
    properties: {}
  action:
    type: service
    domain: light
    service: turn_on
    target:
      entity_id: light.porch
    # data: {}          # optional — service_data, may contain "{{ }}" templates
    # response: false   # optional — true returns the service's response as JSON</code></pre>
      </section>

      <section>
        <h4><code>template</code> — render a Jinja2 template</h4>
        <pre><code>- name: kitchen_temperature
  description: Read the current kitchen temperature.
  parameters:
    type: object
    properties: {}
  action:
    type: template
    value_template: "{{ states('sensor.kitchen_temperature') }}"</code></pre>
      </section>

      <section>
        <h4><code>rest</code> — call an HTTP endpoint</h4>
        <pre><code>- name: lookup_weather
  description: Look up the weather for a city.
  parameters:
    type: object
    properties:
      city:
        type: string
    required: [city]
  action:
    type: rest
    method: GET                 # GET, POST, PUT or DELETE
    url: "https://api.example.com/weather?city={{ city }}"
    response_format: json       # "text" (default) or "json"
    # headers: {}                # optional; values may template too
    # payload: {}                 # optional JSON body (POST/PUT)
    # timeout: 10                 # seconds, 1-120</code></pre>
      </section>

      <section>
        <h4><code>script</code> — run a Home Assistant script</h4>
        <pre><code>- name: run_goodnight
  description: Run the goodnight script.
  parameters:
    type: object
    properties: {}
  action:
    type: script
    script: script.goodnight
    # variables: {}   # optional, passed to the script</code></pre>
      </section>

      <section>
        <h4><code>mcp</code> — tools from a connected MCP server</h4>
        <p>Not written as an <code>action</code> by hand, and not buildable above either.
        Add a server under <code>mcp_servers:</code> instead, and every tool it exposes is
        registered automatically, named <code>&lt;prefix or server name&gt;__&lt;tool name&gt;</code>:</p>
        <pre><code>mcp_servers:
  - name: files
    transport: stdio            # stdio, sse or http
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/share"]
    # prefix: ""                 # "" = no prefix; omitted = use the server name
    # include_tools: []          # only these MCP tool names; unfiltered if empty
    # exclude_tools: []          # drop these MCP tool names</code></pre>
      </section>

      <section>
        <h4>Arguments</h4>
        <p>Keys under <code>parameters.properties</code> define the tool's call
        signature; the LLM's call is validated against it (as JSON Schema) before
        the action runs. Inside <code>service</code>/<code>template</code>/<code>rest</code>/<code>script</code>
        actions, reference an argument by its bare name in a Jinja2 template —
        <code>{{ city }}</code>, not <code>{{ args.city }}</code>.</p>
      </section>

      <section>
        <h4>Secrets</h4>
        <p>Use <code>!secret name</code> anywhere a value comes from
        <code>secrets.yaml</code>, e.g. <code>api_key: !secret weather_api_key</code>.
        This editor always shows the reference itself, never the resolved value —
        Home Assistant only resolves a secret when it loads the file, not when
        this panel reads it back to display it. Importing a file that uses
        <code>!secret</code> is refused for the same reason: importing would have to
        resolve it, and the resolved value would be written into Home Assistant's
        storage as plain text.</p>
      </section>

      <section>
        <h4>Memory (optional)</h4>
        <pre><code>memory:
  stores:
    - name: home_notes
      embeddings: My OpenAI Embeddings   # an Embeddings subentry's title</code></pre>
        <p>Stores are also buildable in the Stores tab, which is the better place —
        a pgvector connection string written here is a password in a text box.</p>
      </section>

      <section>
        <h4>Restricting tools per agent</h4>
        <p>Each agent has its own "Allowed tools" setting (in that agent's options,
        not in this file). Leave it unset to allow every registered tool, including
        MCP tools by their prefixed name; set it to restrict the agent to just the
        names listed. Note that it filters <em>custom</em> tools only — the built-in
        tools an agent has switched on (<code>get_state_history</code>,
        <code>ask_agent</code>, <code>ask_agents</code>, <code>critique_response</code>,
        <code>search_memory</code>, <code>search_entities</code>) are added regardless
        of what is listed there.</p>
      </section>

    </div>
  </details>
`;

const SOURCE_LABELS = {
  subentry: "built here",
  yaml: "tools.yaml",
  mcp: "MCP server",
};

/**
 * <sc-tools-tab> — a constructor for custom tools, plus tools.yaml import/export.
 *
 * A tool used to exist only as an entry in tools.yaml, so building one meant
 * remembering a schema. It is now a config subentry built through a form: the
 * backend serialises the whole constructor (`smartchain/tool/schema`) and
 * <sc-config-form> renders it, exactly as the agents, embeddings and stores
 * tabs do. **No field name of the tool form appears in this file** — including
 * the two that reshape the form, which arrive as `reactive` from the same
 * command.
 *
 * The YAML editor is still here, demoted into "Import / Export": tools.yaml
 * remains a supported source (and the only one for `mcp_servers:`), it is just
 * no longer the only way to write a tool.
 *
 * Home Assistant calls `set hass` on every state change in the house. The
 * `<textarea>` node created in `_render()` is never replaced for the lifetime
 * of this element, and `_paintEditor()` (which sets its `.value`) is only ever
 * invoked from an explicit, user-triggered `reload()` — never from a `hass`
 * tick — so nothing can repaint over text the user is in the middle of typing.
 * `_paintList()` rewrites a different container entirely, and refuses to run at
 * all while a tool form is open.
 *
 * Properties: .hass, .entries
 */
export class ScToolsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._rawEntries = null;
    this._list = null; // {tools, shadowed_yaml} from tool/list
    this._editing = null; // {entryId, subentryId|null}

    this._loaded = false; // becomes true once the first tools/get resolves
    this._busy = false;
    this._state = null; // {path, text, exists, error, hash, backup_exists}
    this._baseline = ""; // text as last loaded/saved — Save disables when equal
    this._baseHash = null; // hash to send with the next save
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    const form = this.querySelector("sc-config-form");
    if (form) form.hass = val;
    if (this._rendered && first) {
      this.reload();
      this._loadList();
    }
  }

  set entries(val) {
    // Home Assistant pushes `hass` on every state change; the shell must not
    // turn that into a repaint. The overview array is a new object only when
    // it has actually been refetched.
    if (val === this._rawEntries) return;
    this._rawEntries = val;
    this._entries = val || [];
    if (!this._rendered) return;
    // Never rebuild out from under a form the user might be filling in.
    if (this._editing) return;
    this._paintList();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._paintList();
    if (this._hass && !this._loaded) {
      this.reload();
      this._loadList();
    }
  }

  _requestRefresh() {
    this.dispatchEvent(new CustomEvent("sc-overview-refresh", { bubbles: true, composed: true }));
  }

  async _loadList() {
    if (!this._hass) return;
    try {
      this._list = await callWS(this._hass, "smartchain/tool/list");
    } catch (err) {
      // A missing list costs the list, not the tab — the YAML editor below
      // still works, which is the escape hatch when something is wrong.
      showToast(err.message || "Could not read the tool list", "error");
      this._list = null;
    }
    if (this._rendered && !this._editing) this._paintList();
  }

  // ---- shell ------------------------------------------------------------

  _render() {
    this.innerHTML = `
      <div class="sc-tools">
        <div class="sc-tools-constructor"></div>
        <details class="sc-tools-help sc-tools-io">
          <summary>Import / Export — tools.yaml</summary>
          <div class="sc-tools-help-body">
            <p>tools.yaml is still read at startup and is the only place
            <code>mcp_servers:</code> can be configured. Import turns the tools in it
            into editable entries above; export writes the entries above back out as
            YAML, with any REST header values blanked.</p>
            <div class="sc-row">
              <mwc-button id="sc-tools-import">Import from tools.yaml</mwc-button>
              <mwc-button id="sc-tools-export">Export to YAML</mwc-button>
            </div>
            <textarea class="sc-tools-editor sc-tools-export sc-hidden" readonly
              spellcheck="false"></textarea>
            <header class="sc-tools-head">
              <span class="sc-tools-path"></span>
              <span class="sc-tools-spacer"></span>
              <mwc-button id="sc-tools-validate">Validate</mwc-button>
              <mwc-button id="sc-tools-rollback" class="sc-hidden">Rollback</mwc-button>
              <mwc-button id="sc-tools-save" raised disabled>Save</mwc-button>
            </header>
            <div class="sc-tools-banner sc-hidden"></div>
            <textarea
              class="sc-tools-editor"
              spellcheck="false"
              autocomplete="off"
              autocapitalize="off"
              placeholder="${escapeHtml(TOOLS_PLACEHOLDER)}"
            ></textarea>
            ${TOOLS_HELP_HTML}
          </div>
        </details>
      </div>
    `;

    // Cache references once — these nodes live for the lifetime of the tab.
    this._els = {
      constructor: this.querySelector(".sc-tools-constructor"),
      path: this.querySelector(".sc-tools-path"),
      banner: this.querySelector(".sc-tools-banner"),
      editor: this.querySelector(".sc-tools-editor:not(.sc-tools-export)"),
      exportBox: this.querySelector(".sc-tools-export"),
      validateBtn: this.querySelector("#sc-tools-validate"),
      saveBtn: this.querySelector("#sc-tools-save"),
      rollbackBtn: this.querySelector("#sc-tools-rollback"),
      importBtn: this.querySelector("#sc-tools-import"),
      exportBtn: this.querySelector("#sc-tools-export"),
    };

    this._els.editor.addEventListener("input", () => this._updateSaveState());
    this._els.validateBtn.addEventListener("click", () => this._validate());
    this._els.saveBtn.addEventListener("click", () => this._save());
    this._els.rollbackBtn.addEventListener("click", () => this._rollback());
    this._els.importBtn.addEventListener("click", () => this._import());
    this._els.exportBtn.addEventListener("click", () => this._export());
  }

  // ---- the constructor --------------------------------------------------

  _paintList() {
    const root = this._els && this._els.constructor;
    if (!root) return;

    if (this._editing) {
      this._paintForm(root);
      return;
    }

    if (!this._entries.length) {
      root.innerHTML = `
        <p class="sc-empty">
          No SmartChain providers are configured yet.
          Add one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    const tools = (this._list && this._list.tools) || [];
    const shadowed = (this._list && this._list.shadowed_yaml) || [];

    root.innerHTML = `
      <section class="sc-entry">
        <header class="sc-entry-head">
          <span class="sc-entry-title">Tools</span>
          <span class="sc-entry-engine">${tools.length} registered</span>
          ${this._addControlHtml()}
        </header>
        ${
          tools.length
            ? `<ul class="sc-embed-list">${tools.map((tool) => this._toolHtml(tool)).join("")}</ul>`
            : `<p class="sc-empty">No custom tools yet. Add one — the form asks for a name,
                 what it does, and what it should do when the model calls it.</p>`
        }
        ${
          shadowed.length
            ? `<p class="sc-empty">Also defined in tools.yaml and ignored in favour of the tool
                 built here: ${escapeHtml(shadowed.join(", "))}. Delete it from tools.yaml to
                 silence this.</p>`
            : ""
        }
      </section>`;

    const add = root.querySelector(".sc-add");
    if (add) {
      add.addEventListener("click", () => {
        this._editing = { entryId: this._chosenEntryId(), subentryId: null };
        this._paintList();
      });
    }
    root.querySelectorAll("[data-act]").forEach((button) =>
      button.addEventListener("click", () => this._act(button.dataset))
    );
  }

  /**
   * Which config entry hosts a new tool. Functionally arbitrary — the tool
   * registry is global and every agent draws from it — so the picker appears
   * only when there is more than one entry to be arbitrary about.
   */
  _addControlHtml() {
    if (this._entries.length === 1) {
      return `<button class="sc-add">+ Tool</button>`;
    }
    return `
      <select class="sc-select sc-tools-owner" title="Which provider stores this tool. Tools are shared by every agent, so this is bookkeeping only.">
        ${this._entries
          .map((entry) => `<option value="${escapeHtml(entry.entry_id)}">${escapeHtml(entry.title)}</option>`)
          .join("")}
      </select>
      <button class="sc-add">+ Tool</button>`;
  }

  _chosenEntryId() {
    const picker = this.querySelector(".sc-tools-owner");
    if (picker) return picker.value;
    return this._entries.length ? this._entries[0].entry_id : null;
  }

  _toolHtml(tool) {
    const source = SOURCE_LABELS[tool.source] || tool.source;
    const editable = tool.source === "subentry";
    const state = tool.enabled ? "" : " · disabled";
    return `
      <li class="sc-embed-row">
        <span class="sc-embed-name">${escapeHtml(tool.name)}${tool.enabled ? "" : " ⚠"}</span>
        <span class="sc-embed-model">${escapeHtml(
          `${tool.action_type || "?"} · ${source}${state}`
        )}</span>
        <span class="sc-embed-actions">
          ${
            editable
              ? `<button data-act="edit" data-entry="${escapeHtml(tool.entry_id)}" data-sub="${escapeHtml(tool.subentry_id)}">Edit</button>
                 <button data-act="del" data-entry="${escapeHtml(tool.entry_id)}" data-sub="${escapeHtml(tool.subentry_id)}">Delete</button>`
              : ""
          }
        </span>
      </li>`;
  }

  _paintForm(root) {
    root.innerHTML = `<sc-config-form></sc-config-form>`;
    const form = root.querySelector("sc-config-form");
    form.hass = this._hass;
    form.commands = TOOL_COMMANDS;
    // A tool form declares no model, so "Refresh models" would refresh nothing
    // it shows.
    form.showRefresh = false;
    // subentryId before entryId: config-form starts loading the moment
    // hass/commands/entryId are all set, so an Edit form's subentryId must
    // already be in place by then — otherwise it would load create-mode
    // defaults and silently discard the existing tool.
    if (this._editing.subentryId) form.subentryId = this._editing.subentryId;
    form.entryId = this._editing.entryId;

    form.addEventListener("sc-saved", (ev) => {
      const detail = ev.detail || {};
      if (detail.reload_error) {
        showToast(`Saved, but the reload failed: ${detail.reload_error}`, "warning");
      } else if (detail.shadows_yaml) {
        showToast("Saved. A tool of this name in tools.yaml is now ignored.", "warning");
      }
      this._editing = null;
      this._paintList();
      this._requestRefresh();
      this._loadList();
    });
    form.addEventListener("sc-cancelled", () => {
      this._editing = null;
      this._paintList();
    });
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    if (act === "edit") {
      this._editing = { entryId, subentryId };
      this._paintList();
      return;
    }

    const tool = ((this._list && this._list.tools) || []).find(
      (candidate) => candidate.subentry_id === subentryId
    );
    const label = tool ? tool.name : "this tool";
    if (!confirm(`Delete "${label}"? Any agent restricted to it loses it immediately.`)) return;

    try {
      const result = await callWS(this._hass, "smartchain/tool/delete", {
        entry_id: entryId,
        subentry_id: subentryId,
      });
      if (result && result.reload_error) {
        showToast(`Deleted, but the reload failed: ${result.reload_error}`, "warning");
      } else {
        showToast("Tool deleted", "success");
      }
    } catch (err) {
      showToast(err.message || "That did not work", "error");
    }
    this._requestRefresh();
    this._loadList();
  }

  // ---- import / export --------------------------------------------------

  async _import() {
    const entryId = this._chosenEntryId();
    if (!entryId) {
      showToast("Configure a provider first — an imported tool has to live somewhere.", "error");
      return;
    }
    if (
      !confirm(
        "Import every tool in tools.yaml as an editable tool?\n\n" +
          "tools.yaml is left exactly as it is — an imported tool shadows its copy " +
          "in the file until you delete that copy yourself."
      )
    ) {
      return;
    }

    this._setBusy(true);
    let result;
    try {
      result = await callWS(this._hass, "smartchain/tools/import", { entry_id: entryId });
    } catch (err) {
      showToast(err.message || "Could not import tools.yaml", "error");
      this._setBusy(false);
      return;
    }
    this._setBusy(false);

    if (!result.ok) {
      showToast(this._importFailureMessage(result), "error");
      return;
    }
    const imported = result.imported || [];
    const skipped = result.skipped || [];
    showToast(
      `Imported ${imported.length} tool(s)` +
        (skipped.length ? `; skipped ${skipped.join(", ")} (name already in use or reserved)` : ""),
      imported.length ? "success" : "info"
    );
    this._requestRefresh();
    this._loadList();
  }

  /**
   * Each refusal describes a different problem, so each gets its own sentence.
   */
  _importFailureMessage(result) {
    switch (result.reason) {
      case "no_file":
        return "There is no tools.yaml to import.";
      case "secrets_present":
        return (
          "tools.yaml uses !secret, so it cannot be imported: importing would have to " +
          "resolve the secret and store the resolved value as plain text. Replace those " +
          "references with values entered in the form above, or keep those tools in the file."
        );
      case "invalid":
        return `tools.yaml is invalid: ${result.error}`;
      default:
        return `Could not import tools.yaml (${result.reason}).`;
    }
  }

  async _export() {
    let result;
    try {
      result = await callWS(this._hass, "smartchain/tools/export");
    } catch (err) {
      showToast(err.message || "Could not export the tools", "error");
      return;
    }
    const { exportBox } = this._els;
    exportBox.value = result.text || "# No tools have been built here yet.\n";
    exportBox.classList.remove("sc-hidden");
    if ((result.redacted || []).length) {
      showToast(
        `Exported ${result.count} tool(s). REST header values were blanked for: ` +
          `${result.redacted.join(", ")} — fill them in before importing this elsewhere.`,
        "warning"
      );
    } else {
      showToast(`Exported ${result.count} tool(s)`, "success");
    }
  }

  // ---- the tools.yaml editor -------------------------------------------

  /**
   * Fetch the file from disk and overwrite the editor with it.
   *
   * Only ever called where overwriting the textarea is the explicit intent:
   * the first load, a user-confirmed "reload after stale" and a refresh after
   * a successful rollback. Never call this from a `hass` tick.
   */
  async reload() {
    this._setBusy(true);
    try {
      this._state = await callWS(this._hass, "smartchain/tools/get");
      this._baseline = this._state.text || "";
      this._baseHash = this._state.hash ?? null;
      this._loaded = true;
    } catch (err) {
      showToast(err.message || "Could not load tools.yaml", "error");
      this._state = null;
    } finally {
      this._setBusy(false);
    }
    this._paintEditor();
  }

  /**
   * Repaint everything that isn't the user's unsaved keystrokes: the path, the
   * error/empty banner, and — deliberately — the textarea's `.value`, which is
   * only safe here because every caller already decided overwriting is correct
   * (see `reload()`). The file text is set as a `.value` assignment, never
   * interpolated into `innerHTML`, so it never touches the escaping surface.
   */
  _paintEditor() {
    const { path, banner, editor } = this._els || {};
    if (!path || !banner || !editor) return;

    editor.value = this._baseline;
    this._updateSaveState();
    // Whether a backup exists is a fact the backend reports, not a guess this
    // session has to make: `tools/get` computes `backup_exists` from the disk
    // so a backup left by an earlier session, or by a restart, still surfaces
    // the Rollback button.
    this._updateRollbackVisibility();

    if (!this._state) {
      path.textContent = "";
      banner.className = "sc-tools-banner sc-tools-error";
      banner.innerHTML = `<ha-icon icon="mdi:alert-circle"></ha-icon> Could not load tools.yaml.`;
      return;
    }

    path.textContent = this._state.path || "";

    if (this._state.error) {
      banner.className = "sc-tools-banner sc-tools-error";
      banner.innerHTML = `<ha-icon icon="mdi:alert-circle"></ha-icon> ${escapeHtml(this._state.error)}`;
      return;
    }

    if (!this._state.exists) {
      banner.className = "sc-tools-banner sc-tools-info";
      banner.innerHTML = `<ha-icon icon="mdi:information"></ha-icon> No tools.yaml at this path — which is fine, and normal: tools built above do not need one. Type here and Save to create it.`;
      return;
    }

    banner.className = "sc-tools-banner sc-hidden";
    banner.innerHTML = "";
  }

  _backupAvailable() {
    return !!(this._state && this._state.backup_exists);
  }

  _setBusy(busy) {
    this._busy = busy;
    if (!this._els) return;
    this._els.validateBtn.toggleAttribute("disabled", busy);
    this._els.rollbackBtn.toggleAttribute("disabled", busy);
    this._els.importBtn.toggleAttribute("disabled", busy);
    this._updateSaveState();
  }

  _updateSaveState() {
    const { editor, saveBtn } = this._els || {};
    if (!editor || !saveBtn) return;
    const unchanged = this._loaded && editor.value === this._baseline;
    saveBtn.toggleAttribute("disabled", this._busy || !this._loaded || unchanged);
  }

  _updateRollbackVisibility() {
    const { rollbackBtn } = this._els || {};
    if (!rollbackBtn) return;
    rollbackBtn.classList.toggle("sc-hidden", !this._backupAvailable());
  }

  async _validate() {
    // Validates the file as it currently sits on disk — the websocket command
    // takes no text, so this checks what was last saved, not whatever is still
    // unsaved in the textarea. Never mutates the editor.
    this._setBusy(true);
    try {
      const result = await callWS(this._hass, "smartchain/tools/validate");
      if (result.valid) {
        showToast("tools.yaml is valid", "success");
      } else {
        showToast(`tools.yaml is invalid: ${result.error}`, "error");
      }
    } catch (err) {
      showToast(err.message || "Could not validate tools.yaml", "error");
    } finally {
      this._setBusy(false);
    }
  }

  async _save() {
    const { editor } = this._els;
    const text = editor.value;

    this._setBusy(true);
    let result;
    try {
      result = await callWS(this._hass, "smartchain/tools/save", {
        text,
        base_hash: this._baseHash,
      });
    } catch (err) {
      showToast(err.message || "Could not save tools.yaml", "error");
      this._setBusy(false);
      return;
    }
    this._setBusy(false);

    if (result.ok) {
      // The baseline becomes the saved text so Save disables again — the
      // textarea itself is untouched, since it already holds exactly this.
      this._baseline = text;
      this._baseHash = result.hash;
      this._state = {
        ...(this._state || {}),
        text,
        exists: true,
        error: null,
        hash: result.hash,
        // A successful save over an existing file always leaves a backup;
        // a first-ever save has nothing to back up. Either way the next
        // `tools/get` re-reads the truth from disk.
        backup_exists: this._state ? !!this._state.exists : false,
      };
      this._updateRollbackVisibility();
      this._updateSaveState();
      // Refresh the banner (clears any stale "no file yet" notice) without
      // touching the textarea's value.
      const { banner } = this._els;
      banner.className = "sc-tools-banner sc-hidden";
      banner.innerHTML = "";
      showToast("tools.yaml saved", "success");
      this._loadList();
      return;
    }

    this._handleSaveFailure(result);
  }

  /**
   * Every refusal reason gets its own message, on purpose — they describe
   * different problems and none of them touches the editor's text. Losing an
   * edit to a failed save would be worse than the failure itself.
   */
  _handleSaveFailure(result) {
    switch (result.reason) {
      case "stale": {
        showToast(
          "Save refused: tools.yaml changed on disk since this editor loaded it.",
          "error",
        );
        const reload = confirm(
          "tools.yaml was changed outside this editor — by another tab, an " +
            "SSH session, or a file editor.\n\n" +
            "Reload it now? This DISCARDS the edit you have not saved here " +
            "and replaces it with what is currently on disk.",
        );
        if (reload) this.reload();
        return;
      }
      case "invalid":
        showToast(`tools.yaml is invalid: ${result.error}`, "error");
        return;
      case "write_failed":
        showToast(`Could not write tools.yaml: ${result.error}`, "error");
        return;
      case "reload_failed":
        // The write succeeded and validated, but the running integration could
        // not adopt it, so the backend restored the previous file — consuming
        // whatever backup made that possible.
        if (this._state) this._state.backup_exists = false;
        this._updateRollbackVisibility();
        showToast(
          `tools.yaml was valid but could not be loaded (${result.error}). ` +
            "The previous file has been restored on disk — your edit here " +
            "has NOT been saved, and is still only in this editor.",
          "error",
        );
        return;
      default:
        showToast(`Could not save tools.yaml (${result.reason}).`, "error");
    }
  }

  async _rollback() {
    if (!this._backupAvailable()) return;
    const proceed = confirm(
      "Roll back tools.yaml to the last backup?\n\n" +
        "This discards what is currently on disk and replaces this editor's " +
        "content with the restored version — any unsaved edit here is lost too.",
    );
    if (!proceed) return;

    this._setBusy(true);
    let result;
    try {
      result = await callWS(this._hass, "smartchain/tools/rollback");
    } catch (err) {
      showToast(err.message || "Could not roll back tools.yaml", "error");
      this._setBusy(false);
      return;
    }
    this._setBusy(false);

    if (!result.ok) {
      if (result.reason === "no_backup") {
        if (this._state) this._state.backup_exists = false;
        this._updateRollbackVisibility();
        showToast("No backup to restore.", "info");
        return;
      }
      // reload_failed — the restore itself succeeded (the .bak is now on disk
      // at the target) but the integration could not adopt it.
      this._updateRollbackVisibility();
      showToast(
        `Rollback restored the file on disk, but the integration could not load it (${result.error}).`,
        "error",
      );
      return;
    }

    showToast("Rolled back to the previous tools.yaml", "success");
    // A rollback is explicit, confirmed consent to discard the editor's
    // contents too (see the confirm() text above) — reload() to show the
    // restored text is the intended outcome, not a stray repaint. It also
    // re-reads `backup_exists`, which the swap has just changed.
    await this.reload();
    this._loadList();
  }
}

customElements.define("sc-tools-tab", ScToolsTab);
