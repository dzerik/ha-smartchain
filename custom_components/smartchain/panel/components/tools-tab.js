import { callWS, escapeHtml, showToast } from "../services.js";

/**
 * Shown via the `<textarea>`'s `placeholder` attribute — native browser
 * behaviour, not a value: it renders only while the field is empty, is never
 * part of `.value`, and disappears the moment the user types a single
 * character. It can therefore never end up on disk, accidentally or
 * otherwise — Save stays disabled until the textarea differs from the
 * loaded baseline, and an untouched empty editor has nothing to save. It is
 * a small, complete, valid tool — see tools/schema.py for the fields this
 * mirrors.
 */
const TOOLS_PLACEHOLDER = `# tools.yaml — custom tools this agent can call.
# This is only a placeholder shown on an empty file; start typing to
# replace it. See "Syntax reference" below for every action type.
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
 * drifts: a syntax reference that disagrees with the validator is worse
 * than no reference at all, because the user cannot tell which one is wrong.
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
        <pre><code>tools:         # custom LLM tools — the bulk of this file
mcp_servers:   # remote MCP servers; their tools are added automatically
memory:        # long-term memory and/or entity indexing</code></pre>
      </section>

      <section>
        <h4>A tool</h4>
        <p>Every entry under <code>tools:</code> needs <code>name</code>, <code>description</code>,
        <code>parameters</code> (a JSON Schema <code>object</code> describing the call's arguments)
        and <code>action</code>. <code>name</code> is lowercase letters, digits and underscores,
        starting with a letter or underscore — and can't be <code>get_state_history</code>,
        <code>ask_agent</code> or <code>search_entities</code>, reserved for built-in tools.
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
        <p>Not written as an <code>action</code> by hand. Add a server under
        <code>mcp_servers:</code> instead, and every tool it exposes is registered
        automatically, named <code>&lt;prefix or server name&gt;__&lt;tool name&gt;</code>:</p>
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
        this panel reads it back to display it.</p>
      </section>

      <section>
        <h4>Memory (optional)</h4>
        <pre><code>memory:
  stores:
    - name: home_notes
      embeddings: My OpenAI Embeddings   # an Embeddings subentry's title</code></pre>
      </section>

      <section>
        <h4>Restricting tools per agent</h4>
        <p>Each agent has its own "Allowed tools" setting (in that agent's options,
        not in this file). Leave it unset to allow every tool registered here,
        including MCP tools by their prefixed name; set it to restrict the agent
        to just the names listed.</p>
      </section>

    </div>
  </details>
`;

/**
 * <sc-tools-tab> — an editor for tools.yaml.
 *
 * Raw text in, raw text out: the textarea holds exactly the bytes on disk,
 * never a parsed-and-re-serialised form, so a `!secret` reference round-trips
 * as a reference. No syntax highlighting, no third-party editor component —
 * the panel has no build step and one isn't worth adding for this.
 *
 * `tools/get` may report `exists: false` (no file at all — the normal
 * first-run state on this install right now, not an error — the user starts
 * typing into an empty editor) or `exists: true` with an `error` (the file is
 * there but unreadable, e.g. permissions or non-UTF-8 bytes); either way the
 * editor stays usable so a broken file can be overwritten outright.
 *
 * The DOM node created for the `<textarea>` in `_render()` is never replaced
 * or recreated for the lifetime of this element. Home Assistant calls
 * `set hass` on every state change in the house; `_paint()` (which sets the
 * textarea's `.value`) is only ever invoked from an explicit, user-triggered
 * `reload()` — never from a `hass` tick — so nothing can repaint over text
 * the user is in the middle of typing. This is the same defect class that
 * made the Create/Edit forms unusable before it was fixed: found only by
 * running the code, never by reading it.
 *
 * Properties: .hass
 */
export class ScToolsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._loaded = false; // becomes true once the first tools/get resolves
    this._busy = false;

    this._state = null; // {path, text, exists, error, hash} from tools/get
    this._baseline = ""; // text as last loaded/saved — Save disables when the
    // textarea matches this
    this._baseHash = null; // hash to send with the next save

    // The backend exposes no "does a backup exist" query — a rollback is
    // discoverable only by attempting it and reading `reason: "no_backup"`.
    // This flag is therefore a local estimate, not a fact read from disk: it
    // starts false (so a fresh page load never offers a rollback it cannot
    // back up) and only becomes true when *this* session just created a
    // backup by saving over a pre-existing file, or after a reload_failed
    // restore that still leaves a backup as the source of that restore. It
    // goes false again the moment that backup is consumed (a successful
    // rollback, or a reload_failed restore, both of which move `.bak` onto
    // the target). A backup that predates this page load — from an earlier
    // session, a restart — will not surface Rollback until the user saves
    // again in this session. Flagged in the task report as a real gap
    // between the design's "appears only when a backup exists" and what the
    // websocket API can actually tell the panel.
    this._backupAvailable = false;
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    if (this._rendered && first) this.reload();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass && !this._loaded) this.reload();
  }

  /**
   * Fetch the file from disk and overwrite the editor with it.
   *
   * Only ever called where overwriting the textarea is the explicit intent:
   * the first load, a user-confirmed "reload after stale" and a refresh
   * after a successful rollback. Never call this from a `hass` tick.
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
    this._paint();
  }

  _render() {
    this.innerHTML = `
      <div class="sc-tools">
        <header class="sc-tools-head">
          <span class="sc-tools-path"></span>
          <span class="sc-tools-spacer"></span>
          <mwc-button id="sc-tools-validate">Validate</mwc-button>
          <mwc-button id="sc-tools-rollback" class="sc-hidden">Rollback</mwc-button>
          <mwc-button id="sc-tools-save" raised disabled>Save</mwc-button>
        </header>
        <div class="sc-tools-banner sc-hidden"></div>
        ${TOOLS_HELP_HTML}
        <textarea
          class="sc-tools-editor"
          spellcheck="false"
          autocomplete="off"
          autocapitalize="off"
          placeholder="${escapeHtml(TOOLS_PLACEHOLDER)}"
        ></textarea>
      </div>
    `;

    // Cache references once — these nodes live for the lifetime of the tab.
    this._els = {
      path: this.querySelector(".sc-tools-path"),
      banner: this.querySelector(".sc-tools-banner"),
      editor: this.querySelector(".sc-tools-editor"),
      validateBtn: this.querySelector("#sc-tools-validate"),
      saveBtn: this.querySelector("#sc-tools-save"),
      rollbackBtn: this.querySelector("#sc-tools-rollback"),
    };

    this._els.editor.addEventListener("input", () => this._updateSaveState());
    this._els.validateBtn.addEventListener("click", () => this._validate());
    this._els.saveBtn.addEventListener("click", () => this._save());
    this._els.rollbackBtn.addEventListener("click", () => this._rollback());
  }

  /**
   * Repaint everything that isn't the user's unsaved keystrokes: the path,
   * the error/empty banner, and — deliberately — the textarea's `.value`,
   * which is only safe here because every caller of `_paint()` already
   * decided overwriting is correct (see `reload()`'s doc comment). The file
   * text is set as a `.value` assignment, never interpolated into
   * `innerHTML`, so it never touches the escaping surface at all.
   */
  _paint() {
    const { path, banner, editor } = this._els || {};
    if (!path || !banner || !editor) return;

    editor.value = this._baseline;
    this._updateSaveState();

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
      banner.innerHTML = `<ha-icon icon="mdi:information"></ha-icon> No tools.yaml yet at this path — that is the normal state until custom tools are configured. Type below and Save to create it.`;
      return;
    }

    banner.className = "sc-tools-banner sc-hidden";
    banner.innerHTML = "";
  }

  _setBusy(busy) {
    this._busy = busy;
    if (!this._els) return;
    this._els.validateBtn.toggleAttribute("disabled", busy);
    this._els.rollbackBtn.toggleAttribute("disabled", busy);
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
    rollbackBtn.classList.toggle("sc-hidden", !this._backupAvailable);
  }

  async _validate() {
    // Validates the file as it currently sits on disk — the websocket
    // command takes no text, so this checks what was last saved, not
    // whatever is still unsaved in the textarea. Never mutates the editor.
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
    // The file that existed (or didn't) immediately before this save — used
    // below to decide whether this save could possibly have created a
    // backup. Captured before any state mutation.
    const hadFileBefore = !!(this._state && this._state.exists && !this._state.error);

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
      this._state = { ...(this._state || {}), text, exists: true, error: null, hash: result.hash };
      if (hadFileBefore) this._backupAvailable = true;
      this._updateRollbackVisibility();
      this._updateSaveState();
      // Refresh the banner (clears any stale "no file yet" notice) without
      // touching the textarea's value.
      const { banner } = this._els;
      banner.className = "sc-tools-banner sc-hidden";
      banner.innerHTML = "";
      showToast("tools.yaml saved", "success");
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
        // The write succeeded and validated, but the running integration
        // could not adopt it, so the backend restored the previous file —
        // consuming whatever backup made that possible.
        this._backupAvailable = false;
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
    if (!this._backupAvailable) return;
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
        this._backupAvailable = false;
        this._updateRollbackVisibility();
        showToast("No backup to restore.", "info");
        return;
      }
      // reload_failed — the restore itself succeeded (the .bak is now on
      // disk at the target) but the integration could not adopt it.
      this._backupAvailable = false;
      this._updateRollbackVisibility();
      showToast(
        `Rollback restored the file on disk, but the integration could not load it (${result.error}).`,
        "error",
      );
      return;
    }

    this._backupAvailable = false;
    showToast("Rolled back to the previous tools.yaml", "success");
    // A rollback is explicit, confirmed consent to discard the editor's
    // contents too (see the confirm() text above) — reload() to show the
    // restored text is the intended outcome, not a stray repaint.
    await this.reload();
  }
}

customElements.define("sc-tools-tab", ScToolsTab);
