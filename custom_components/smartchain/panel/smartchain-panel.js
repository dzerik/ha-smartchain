import { SC_STYLES } from "./styles.js";
import { showConfirm, showToast } from "./services.js";
import "./components/sidebar-explorer.js";
import "./components/code-editor.js";
import "./components/ai-bar.js";
import "./components/toolbar.js";
import "./components/camera-tab.js";

/**
 * <smartchain-panel> — IDE-like panel for SmartChain.
 *
 * Two modes:
 *   1. Editor — sidebar (explorer) + main (toolbar, Monaco, AI bar)
 *   2. Camera — camera analysis tab
 */
class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this._mode = "editor";
    this._originalYaml = "";
    this._currentType = "automation";
    this._currentAlias = "";
    this._currentId = null;
    this._diffVisible = false;
    this._sidebarCollapsed = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    this._propagateHass();
  }

  _propagateHass() {
    for (const sel of ["sc-sidebar-explorer", "sc-ai-bar", "sc-toolbar", "sc-camera-tab"]) {
      const el = this.querySelector(sel);
      if (el) el.hass = this._hass;
    }
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>

      <div class="sc-mode-tabs">
        <button class="sc-sidebar-toggle" title="Toggle sidebar">
          <ha-icon icon="mdi:menu"></ha-icon>
        </button>
        <button class="sc-mode-tab active" data-mode="editor">
          <ha-icon icon="mdi:code-tags"></ha-icon> Editor
        </button>
        <button class="sc-mode-tab" data-mode="camera">
          <ha-icon icon="mdi:camera"></ha-icon> Camera
        </button>
      </div>

      <!-- Editor mode -->
      <div class="sc-ide" id="mode-editor">
        <div class="sc-sidebar">
          <div class="sc-sidebar-header">
            <ha-icon icon="mdi:robot"></ha-icon>
            <span>SmartChain</span>
          </div>
          <sc-sidebar-explorer></sc-sidebar-explorer>
        </div>

        <div class="sc-main">
          <sc-toolbar></sc-toolbar>
          <div class="sc-editor-area">
            <sc-code-editor></sc-code-editor>
          </div>
          <sc-ai-bar></sc-ai-bar>
          <div class="sc-statusbar">
            <span class="sb-lines">0 lines</span>
            <span class="sb-type">yaml</span>
            <span class="sb-id"></span>
            <span style="margin-left:auto;color:var(--disabled-text-color,#999);font-size:11px;">
              Ctrl+Shift+V validate &middot; Ctrl+Shift+D deploy &middot; Ctrl+Shift+G diff &middot; Ctrl+Enter AI
            </span>
          </div>
        </div>
      </div>

      <!-- Camera mode -->
      <div class="sc-hidden" id="mode-camera">
        <div class="sc-camera-container">
          <sc-camera-tab></sc-camera-tab>
        </div>
      </div>
    `;

    this._setupModeSwitch();
    this._setupSidebar();
    this._setupToolbar();
    this._setupEditor();
    this._setupAiBar();
    this._propagateHass();
  }

  /* ---- Mode Switch ---- */
  _setupModeSwitch() {
    this.querySelectorAll(".sc-mode-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        this.querySelectorAll(".sc-mode-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        this._mode = tab.dataset.mode;
        this.querySelector("#mode-editor").classList.toggle("sc-hidden", this._mode !== "editor");
        this.querySelector("#mode-camera").classList.toggle("sc-hidden", this._mode !== "camera");
      });
    });

    this.querySelector(".sc-sidebar-toggle").addEventListener("click", () => {
      this._sidebarCollapsed = !this._sidebarCollapsed;
      this.querySelector(".sc-sidebar").classList.toggle("collapsed", this._sidebarCollapsed);
    });
  }

  /* ---- Sidebar ---- */
  _setupSidebar() {
    const sidebar = this.querySelector("sc-sidebar-explorer");

    sidebar.addEventListener("select", async (e) => {
      const { yaml, type, id, alias } = e.detail;
      if (!(await this._confirmUnsavedChanges())) return;
      this._loadYaml(yaml, type, id, alias);
    });

    sidebar.addEventListener("new", async () => {
      if (!(await this._confirmUnsavedChanges())) return;
      this._newFile();
    });
  }

  async _confirmUnsavedChanges() {
    const editor = this.querySelector("sc-code-editor");
    const currentValue = editor?.value || "";
    if (currentValue !== this._originalYaml && currentValue.trim() !== "") {
      return await showConfirm(
        "Unsaved Changes",
        "You have unsaved changes. Discard them and switch to another file?",
        "Discard",
        "sc-btn-warn"
      );
    }
    return true;
  }

  /* ---- Toolbar ---- */
  _setupToolbar() {
    const toolbar = this.querySelector("sc-toolbar");
    const editor = this.querySelector("sc-code-editor");
    toolbar.getYaml = () => editor?.value || "";

    toolbar.addEventListener("action", (e) => {
      const { action } = e.detail;
      switch (action) {
        case "diff": this._toggleDiff(); break;
        case "diff-prev": editor.goToPrevDiff(); break;
        case "diff-next": editor.goToNextDiff(); break;
        case "diff-toggle-mode": editor.renderSideBySide = e.detail.sideBySide; break;
        case "diff-accept": this._acceptDiff(); break;
        case "diff-revert": this._revertDiff(); break;
      }
    });
  }

  /* ---- Editor ---- */
  _setupEditor() {
    const editor = this.querySelector("sc-code-editor");

    editor.addEventListener("change", (e) => {
      const val = e.detail.value;
      const toolbar = this.querySelector("sc-toolbar");
      toolbar.dirty = val !== this._originalYaml;

      const aiBar = this.querySelector("sc-ai-bar");
      if (aiBar) aiBar.currentYaml = val;

      this._updateStatusBar(val);
    });

    editor.addEventListener("diff-updated", () => this._updateDiffStats());

    editor.addEventListener("action", (e) => {
      const { id } = e.detail;
      const toolbar = this.querySelector("sc-toolbar");
      if (id === "validate") toolbar.querySelector(".tb-validate")?.click();
      else if (id === "deploy") toolbar.querySelector(".tb-deploy")?.click();
      else if (id === "diff") this._toggleDiff();
      else if (id === "ai-apply") {
        const input = this.querySelector("sc-ai-bar .ab-input");
        if (input) input.focus();
      }
    });
  }

  /* ---- AI Bar ---- */
  _setupAiBar() {
    const aiBar = this.querySelector("sc-ai-bar");
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");

    aiBar.addEventListener("result", (e) => {
      const { yaml } = e.detail;
      const previousYaml = editor.value;

      editor.originalValue = previousYaml || this._originalYaml;
      editor.value = yaml;
      editor.diffMode = true;
      this._diffVisible = true;
      toolbar.diffActive = true;
      toolbar.dirty = yaml !== this._originalYaml;

      this._updateStatusBar(yaml);
    });
  }

  /* ---- File Operations ---- */
  _loadYaml(yaml, type, id, alias) {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");
    const aiBar = this.querySelector("sc-ai-bar");

    this._originalYaml = yaml;
    this._currentType = type;
    this._currentAlias = alias;
    this._currentId = id;

    editor.forceNormalMode(yaml);
    this._diffVisible = false;
    toolbar.diffActive = false;
    toolbar.title = `${alias} (${type})`;
    toolbar.dirty = false;
    toolbar.currentType = type;
    aiBar.currentYaml = yaml;
    aiBar.currentType = type;
    aiBar.setType(type);

    this._updateStatusBar(yaml);
  }

  _newFile() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");
    const aiBar = this.querySelector("sc-ai-bar");
    const sidebar = this.querySelector("sc-sidebar-explorer");

    this._originalYaml = "";
    this._currentAlias = "";
    this._currentId = null;

    editor.forceNormalMode("");
    this._diffVisible = false;
    toolbar.diffActive = false;
    toolbar.title = "New";
    toolbar.dirty = false;
    aiBar.currentYaml = "";
    sidebar.setActive(null, null);

    this._updateStatusBar("");
  }

  /* ---- Diff ---- */
  _toggleDiff() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");

    this._diffVisible = !this._diffVisible;
    if (this._diffVisible) editor.originalValue = this._originalYaml;
    editor.diffMode = this._diffVisible;
    toolbar.diffActive = this._diffVisible;
  }

  _acceptDiff() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");

    this._originalYaml = editor.value;
    editor.acceptChanges();
    this._diffVisible = false;
    toolbar.diffActive = false;
    toolbar.dirty = false;
    showToast("Changes accepted", "success", 2000);
  }

  _revertDiff() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");

    editor.revertChanges();
    this._diffVisible = false;
    toolbar.diffActive = false;
    toolbar.dirty = false;
    showToast("Reverted to original", "info", 2000);
  }

  _updateDiffStats() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");
    const stats = editor.getDiffStats();
    toolbar.updateDiffStats(stats);
  }

  /* ---- Status Bar ---- */
  _updateStatusBar(yaml) {
    const lines = (yaml || "").split("\n").length;
    const linesEl = this.querySelector(".sb-lines");
    const typeEl = this.querySelector(".sb-type");
    const idEl = this.querySelector(".sb-id");
    if (linesEl) linesEl.textContent = `${lines} line${lines !== 1 ? "s" : ""}`;
    if (typeEl) typeEl.textContent = this._currentType;
    if (idEl) idEl.textContent = this._currentId ? `id: ${this._currentId}` : "";
  }
}

customElements.define("smartchain-panel", SmartChainPanel);
