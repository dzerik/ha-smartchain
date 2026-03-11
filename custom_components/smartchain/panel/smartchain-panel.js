import { SC_STYLES } from "./styles.js";
import "./components/sidebar-explorer.js";
import "./components/code-editor.js";
import "./components/diff-viewer.js";
import "./components/ai-bar.js";
import "./components/toolbar.js";
import "./components/camera-tab.js";

/**
 * <smartchain-panel> — IDE-like panel for SmartChain.
 *
 * Two modes:
 *   1. Editor — two-column layout: sidebar (explorer) + main (toolbar, editor, diff, AI bar)
 *   2. Camera — camera analysis tab
 */
class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this._mode = "editor"; // "editor" | "camera"
    this._originalYaml = "";
    this._currentType = "automation";
    this._currentAlias = "";
    this._currentId = null;
    this._diffVisible = false;
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
    const sidebar = this.querySelector("sc-sidebar-explorer");
    const aiBar = this.querySelector("sc-ai-bar");
    const toolbar = this.querySelector("sc-toolbar");
    const camTab = this.querySelector("sc-camera-tab");
    if (sidebar) sidebar.hass = this._hass;
    if (aiBar) aiBar.hass = this._hass;
    if (toolbar) toolbar.hass = this._hass;
    if (camTab) camTab.hass = this._hass;
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>

      <!-- Mode tabs -->
      <div class="sc-mode-tabs">
        <button class="sc-mode-tab active" data-mode="editor">\u2699 Editor</button>
        <button class="sc-mode-tab" data-mode="camera">\uD83D\uDCF7 Camera</button>
      </div>

      <!-- Editor mode -->
      <div class="sc-ide" id="mode-editor">
        <!-- Left sidebar -->
        <div class="sc-sidebar">
          <div class="sc-sidebar-header">
            <ha-icon icon="mdi:robot"></ha-icon>
            <span>SmartChain</span>
          </div>
          <sc-sidebar-explorer></sc-sidebar-explorer>
        </div>

        <!-- Right main area -->
        <div class="sc-main">
          <sc-toolbar></sc-toolbar>
          <div class="sc-editor-area">
            <sc-code-editor></sc-code-editor>
            <sc-diff-viewer></sc-diff-viewer>
          </div>
          <sc-ai-bar></sc-ai-bar>
          <div class="sc-statusbar">
            <span class="sb-lines">0 lines</span>
            <span class="sb-type">automation</span>
            <span class="sb-id"></span>
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
  }

  _setupSidebar() {
    const sidebar = this.querySelector("sc-sidebar-explorer");

    sidebar.addEventListener("select", (e) => {
      const { yaml, type, id, alias } = e.detail;
      this._loadYaml(yaml, type, id, alias);
    });

    sidebar.addEventListener("new", () => {
      this._newFile();
    });
  }

  _setupToolbar() {
    const toolbar = this.querySelector("sc-toolbar");
    toolbar.getYaml = () => this.querySelector("sc-code-editor")?.value || "";

    toolbar.addEventListener("action", (e) => {
      const { action } = e.detail;
      if (action === "diff") {
        this._toggleDiff();
      }
    });
  }

  _setupEditor() {
    const editor = this.querySelector("sc-code-editor");

    editor.addEventListener("change", () => {
      const toolbar = this.querySelector("sc-toolbar");
      const val = editor.value;
      const isDirty = val !== this._originalYaml;
      toolbar.dirty = isDirty;

      // Update AI bar
      const aiBar = this.querySelector("sc-ai-bar");
      if (aiBar) aiBar.currentYaml = val;

      // Update diff
      const diff = this.querySelector("sc-diff-viewer");
      if (diff && diff.visible) {
        diff.newText = val;
      }

      // Update status bar
      this._updateStatusBar(val);
    });
  }

  _setupAiBar() {
    const aiBar = this.querySelector("sc-ai-bar");
    const editor = this.querySelector("sc-code-editor");
    const diff = this.querySelector("sc-diff-viewer");
    const toolbar = this.querySelector("sc-toolbar");

    aiBar.addEventListener("result", (e) => {
      const { yaml } = e.detail;
      const previousYaml = editor.value;

      // Set new value
      editor.value = yaml;

      // Show diff automatically
      diff.oldText = previousYaml || this._originalYaml;
      diff.newText = yaml;
      diff.visible = true;
      this._diffVisible = true;
      toolbar.diffActive = true;
      toolbar.dirty = yaml !== this._originalYaml;

      this._updateStatusBar(yaml);
    });
  }

  _loadYaml(yaml, type, id, alias) {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");
    const aiBar = this.querySelector("sc-ai-bar");
    const diff = this.querySelector("sc-diff-viewer");

    this._originalYaml = yaml;
    this._currentType = type;
    this._currentAlias = alias;
    this._currentId = id;

    editor.value = yaml;
    toolbar.title = `${alias} (${type})`;
    toolbar.dirty = false;
    toolbar.currentType = type;
    aiBar.currentYaml = yaml;
    aiBar.currentType = type;
    aiBar.setType(type);

    // Reset diff
    diff.oldText = yaml;
    diff.newText = yaml;
    if (this._diffVisible) {
      diff.visible = true;
    }

    this._updateStatusBar(yaml);
    editor.focus();
  }

  _newFile() {
    const editor = this.querySelector("sc-code-editor");
    const toolbar = this.querySelector("sc-toolbar");
    const aiBar = this.querySelector("sc-ai-bar");
    const diff = this.querySelector("sc-diff-viewer");
    const sidebar = this.querySelector("sc-sidebar-explorer");

    this._originalYaml = "";
    this._currentAlias = "";
    this._currentId = null;

    editor.value = "";
    toolbar.title = "New";
    toolbar.dirty = false;
    aiBar.currentYaml = "";
    diff.visible = false;
    this._diffVisible = false;
    toolbar.diffActive = false;
    sidebar.setActive(null, null);

    this._updateStatusBar("");
    editor.focus();
  }

  _toggleDiff() {
    const diff = this.querySelector("sc-diff-viewer");
    const toolbar = this.querySelector("sc-toolbar");
    const editor = this.querySelector("sc-code-editor");

    this._diffVisible = !this._diffVisible;
    diff.oldText = this._originalYaml;
    diff.newText = editor.value;
    diff.visible = this._diffVisible;
    toolbar.diffActive = this._diffVisible;
  }

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
