/**
 * SmartChain Panel — Design tokens & shared styles for every tab.
 */
export const SC_STYLES = `
  :host { display: block; }

  smartchain-panel {
    --sc-font: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    --sc-radius-sm: 6px;
    --sc-radius-md: 10px;
    --sc-radius-lg: 14px;
    --sc-shadow: 0 2px 8px rgba(0,0,0,0.08);
    --sc-shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
    --sc-transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .sc-hidden { display: none !important; }

  .sc-card {
    background: var(--card-background-color, #fff);
    border-radius: var(--sc-radius-lg);
    padding: 28px;
    box-shadow: var(--sc-shadow);
    margin-bottom: 16px;
  }
  .sc-card h2 { margin: 0 0 8px 0; font-size: 18px; font-weight: 600; }
  .sc-card p { margin: 0 0 20px 0; color: var(--secondary-text-color); font-size: 14px; line-height: 1.5; }

  .sc-textarea {
    width: 100%;
    min-height: 60px;
    padding: 12px 14px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--sc-radius-md);
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-family: inherit;
    font-size: 14px;
    resize: vertical;
    box-sizing: border-box;
    transition: border-color var(--sc-transition);
  }
  .sc-textarea:focus { outline: none; border-color: var(--primary-color, #03a9f4); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent); }

  .sc-select {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--sc-radius-sm);
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-size: 14px;
    box-sizing: border-box;
    transition: border-color var(--sc-transition);
  }
  .sc-select:focus { outline: none; border-color: var(--primary-color); }

  .sc-row { display: flex; gap: 12px; }
  .sc-row > * { flex: 1; min-width: 0; }

  .sc-label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--secondary-text-color);
    margin-bottom: 6px;
  }

  .sc-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 18px;
    border: none;
    border-radius: var(--sc-radius-sm);
    background: var(--primary-color, #03a9f4);
    color: #fff;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color var(--sc-transition), opacity var(--sc-transition);
  }
  .sc-btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .sc-btn-primary { background: var(--primary-color, #03a9f4); }
  .sc-btn-primary:hover:not(:disabled) { filter: brightness(1.1); }
  .sc-btn ha-icon { --mdc-icon-size: 18px; }

  /* ========== Toast Notifications ========== */
  .sc-toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 10000;
    display: flex;
    flex-direction: column-reverse;
    gap: 8px;
    pointer-events: none;
    /* Errors wait for the reader now, so the stack has no natural ceiling.
       Cap it at the viewport and let it scroll: the wheel lands on a toast,
       whose pointer-events: auto puts it in the hit test, and the scroll
       chains up to here. The max-width keeps a long toast on a phone from
       running off the left edge. */
    max-width: calc(100vw - 48px);
    max-height: calc(100vh - 48px);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .sc-toast {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 16px 12px 20px;
    border-radius: var(--sc-radius-md);
    font-size: 13px;
    font-weight: 500;
    box-shadow: var(--sc-shadow-lg);
    pointer-events: auto;
    animation: sc-toast-in 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    max-width: 420px;
    line-height: 1.4;
  }
  .sc-toast ha-icon { --mdc-icon-size: 20px; flex-shrink: 0; }
  /* A reload_failed toast is a paragraph. It must wrap inside the toast
     rather than widen it, and min-width:0 is what lets a flex item wrap at all. */
  .sc-toast-text { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
  .sc-toast-close {
    appearance: none;
    border: none;
    background: none;
    color: inherit;
    flex: 0 0 auto;
    padding: 0 2px;
    margin-left: 2px;
    font-size: 15px;
    line-height: 1.4;
    opacity: 0.85;
    cursor: pointer;
    border-radius: 4px;
  }
  .sc-toast-close:hover { opacity: 1; }
  .sc-toast-close:focus-visible { outline: 2px solid currentColor; outline-offset: 1px; opacity: 1; }
  .sc-toast-success { background: var(--success-color, #4caf50); color: #fff; }
  .sc-toast-error { background: var(--error-color, #f44336); color: #fff; }
  .sc-toast-info { background: var(--primary-color, #03a9f4); color: #fff; }
  .sc-toast-warning { background: var(--warning-color, #ff9800); color: #fff; }
  .sc-toast-out { animation: sc-toast-out 0.25s ease-in forwards; }
  @keyframes sc-toast-in { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
  @keyframes sc-toast-out { from { opacity: 1; } to { transform: translateY(10px); opacity: 0; } }

  /* ========== Tab Shell ========== */
  .sc-tabs-row {
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    background: var(--primary-background-color, #fafafa);
  }
  /* flex: 1 alone leaves min-width at its auto default, which is the
     content width — the strip then refuses to shrink and shoves the version
     label out of the window instead of scrolling. min-width: 0 is what makes
     the overflow-x below reachable. */
  .sc-tabs-row .sc-tabs {
    border-bottom: none;
    background: none;
    flex: 1 1 auto;
    min-width: 0;
  }
  .sc-version {
    padding: 0 16px;
    font-size: 12px;
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .sc-tabs {
    display: flex;
    gap: 4px;
    padding: 0 16px;
    /* Six tabs are ~700px wide; a phone is 360px. Without this the tabs past
       the edge are not merely ugly, they are unreachable — there is no other
       way into those tabs. */
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: thin;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    background: var(--primary-background-color, #fafafa);
  }
  .sc-tab {
    appearance: none;
    border: none;
    background: none;
    flex: 0 0 auto;
    white-space: nowrap;
    padding: 14px 16px;
    font-size: 14px;
    font-weight: 500;
    color: var(--secondary-text-color);
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }
  .sc-tab:hover { color: var(--primary-text-color); }
  .sc-tab-active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }
  .sc-tab-body {
    margin: 0 auto;
    padding: 24px;
    font-family: var(--sc-font);
    color: var(--primary-text-color, #212121);
  }
  sc-camera-tab { display: block; max-width: 800px; margin: 0 auto; }
  sc-agents-tab, sc-embeddings-tab, sc-stores-tab, sc-settings-tab, sc-tools-tab { display: block; max-width: 1100px; margin: 0 auto; }

  /* Narrow screens. 28px of card padding plus 24px of body padding takes 104px
     of a 360px phone before any content is drawn, and a two-up .sc-row leaves
     each select too narrow to read an entity name in. */
  @media (max-width: 600px) {
    .sc-tab-body { padding: 16px 12px; }
    .sc-card { padding: 20px 16px; }
    .sc-tabs { padding: 0 8px; }
    .sc-tab { padding: 14px 10px; font-size: 13px; }
    .sc-version { padding: 0 10px; }
    .sc-row { flex-direction: column; }
  }

  /* ========== Agents Tab ========== */
  .sc-entry { margin-bottom: 24px; }
  .sc-entry-head {
    display: flex; align-items: center; gap: 12px;
    padding-bottom: 8px; border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-entry-title { font-weight: 500; }
  .sc-entry-engine { color: var(--secondary-text-color); font-size: 13px; }
  .sc-entry-head .sc-add { margin-left: auto; }
  .sc-agent-list { list-style: none; margin: 0; padding: 0; }
  .sc-agent-row {
    display: grid;
    grid-template-columns: 1fr 1fr auto auto;
    gap: 12px; align-items: center;
    padding: 10px 0; border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-agent-model, .sc-agent-tools {
    color: var(--secondary-text-color); font-size: 13px;
  }
  .sc-agent-tools summary { cursor: pointer; }
  .sc-tool-inventory-list { list-style: none; margin: 6px 0 0; padding: 0; }
  .sc-tool-inventory-list li {
    display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; padding: 2px 0;
  }
  .sc-tool-inventory-list code { font-size: 12px; color: var(--primary-text-color); }
  /* A tool that is off must read as off at a glance, not only by its reason. */
  .sc-tool-off code { text-decoration: line-through; color: var(--secondary-text-color); }
  .sc-tool-source {
    font-size: 11px; padding: 1px 6px; border-radius: 10px;
    border: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-tool-reason { font-size: 11px; font-style: italic; }
  .sc-agent-actions { display: flex; gap: 8px; }
  .sc-agent-actions button, .sc-add {
    appearance: none; border: 1px solid var(--divider-color, #e0e0e0);
    background: none; border-radius: 6px; padding: 4px 10px;
    font-size: 13px; color: var(--primary-text-color); cursor: pointer;
  }
  .sc-agent-actions button:hover, .sc-add:hover {
    border-color: var(--primary-color, #03a9f4);
    color: var(--primary-color, #03a9f4);
  }
  .sc-empty { color: var(--secondary-text-color); font-size: 14px; }
  @media (max-width: 600px) {
    .sc-agent-row { grid-template-columns: 1fr; gap: 4px; }
  }

  /* ========== Embeddings Tab ========== */
  .sc-embed-list { list-style: none; margin: 0; padding: 0; }
  .sc-embed-row {
    display: grid;
    grid-template-columns: 1fr 1fr auto;
    gap: 12px; align-items: center;
    padding: 10px 0; border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-embed-model { color: var(--secondary-text-color); font-size: 13px; }
  .sc-embed-actions { display: flex; gap: 8px; }
  .sc-embed-actions button {
    appearance: none; border: 1px solid var(--divider-color, #e0e0e0);
    background: none; border-radius: 6px; padding: 4px 10px;
    font-size: 13px; color: var(--primary-text-color); cursor: pointer;
  }
  .sc-embed-actions button:hover {
    border-color: var(--primary-color, #03a9f4);
    color: var(--primary-color, #03a9f4);
  }
  @media (max-width: 600px) {
    .sc-embed-row { grid-template-columns: 1fr; gap: 4px; }
  }

  /* ========== Stores Tab ========== */
  .sc-store-list { list-style: none; margin: 0 0 12px; padding: 0; }
  .sc-store-status {
    display: grid;
    grid-template-columns: 1fr 1fr 2fr;
    gap: 12px; align-items: baseline;
    padding: 8px 0 8px 10px;
    border-left: 3px solid var(--divider-color, #e0e0e0);
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-store-status.sc-ok { border-left-color: var(--success-color, #43a047); }
  .sc-store-status.sc-bad { border-left-color: var(--error-color, #db4437); }
  .sc-store-name { font-weight: 500; }
  .sc-store-origin { color: var(--secondary-text-color); font-size: 13px; }
  .sc-store-reason { color: var(--secondary-text-color); font-size: 13px; }
  .sc-store-status.sc-bad .sc-store-reason { color: var(--error-color, #db4437); }
  /* The store form cannot be filled in at all — see NO_BINDINGS_NOTICE. */
  .sc-store-blocked {
    color: var(--error-color, #db4437);
    border-left: 3px solid var(--error-color, #db4437);
    padding: 8px 10px; margin: 0 0 12px;
  }
  @media (max-width: 600px) {
    .sc-store-status { grid-template-columns: 1fr; gap: 4px; }
  }

  /* ========== Settings Tab ========== */
  .sc-entry-picker { list-style: none; margin: 0; padding: 0; }
  .sc-entry-picker li { margin-bottom: 8px; }
  .sc-entry-pick {
    display: flex; align-items: center; gap: 12px; width: 100%;
    appearance: none; border: 1px solid var(--divider-color, #e0e0e0);
    background: var(--card-background-color, #fff); border-radius: var(--sc-radius-sm);
    padding: 12px 16px; font-size: 14px; color: var(--primary-text-color);
    cursor: pointer; text-align: left;
  }
  .sc-entry-pick:hover { border-color: var(--primary-color, #03a9f4); }
  .sc-entry-pick .sc-entry-engine { margin-left: auto; }

  /* ========== Tools Tab ========== */
  /* The tools.yaml editor is no longer the tab — it is the escape hatch under
     it, so it gets breathing room above and a picker that lines up with the
     Add button beside it. */
  .sc-tools-io { margin-top: 20px; }
  /* The ready-made catalogue. Its blurb is a sentence rather than a model
     name, so the middle column gets the room the tool list does not need. */
  .sc-presets .sc-empty { margin: 8px 0 4px; }
  .sc-preset-row { grid-template-columns: minmax(140px, 1fr) 2fr auto; }
  .sc-preset-row .sc-embed-actions { align-items: center; }
  @media (max-width: 600px) {
    .sc-preset-row { grid-template-columns: 1fr; }
  }
  .sc-tools-export { min-height: 160px; margin-bottom: 12px; }
  .sc-entry-head .sc-tools-owner { max-width: 220px; margin-left: auto; }
  .sc-entry-head .sc-tools-owner + .sc-add { margin-left: 8px; }
  .sc-tools-head {
    display: flex; align-items: center; gap: 12px;
    padding-bottom: 12px; margin-bottom: 12px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-tools-path {
    font-family: var(--code-font-family, monospace);
    font-size: 13px; color: var(--secondary-text-color);
    overflow-wrap: anywhere;
  }
  .sc-tools-spacer { flex: 1; }
  .sc-tools-editor {
    display: block;
    width: 100%;
    min-height: 480px;
    margin: 0;
    padding: 16px;
    font-family: var(--code-font-family, monospace);
    font-size: 13px;
    line-height: 1.6;
    white-space: pre;
    overflow: auto;
    /* Home Assistant resolves --code-editor-background-color from the theme —
       on a light theme it is the card background, i.e. white — so the literal
       #d4d4d4 ink that used to sit here read at about 1.3:1. Both halves of
       the pair must come from the same theme, fallbacks included: a fixed dark
       slab under a themed ink fails the same way from the other side. */
    background: var(--code-editor-background-color, var(--card-background-color, #fff));
    color: var(--primary-text-color, #212121);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--sc-radius-md);
    box-sizing: border-box;
    resize: vertical;
    tab-size: 2;
  }
  .sc-tools-editor:focus {
    outline: none;
    border-color: var(--primary-color, #03a9f4);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent);
  }
  .sc-tools-banner {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px;
    margin-bottom: 12px;
    border-radius: var(--sc-radius-sm);
    font-size: 14px;
  }
  .sc-tools-error {
    color: var(--error-color, #f44336);
    background: color-mix(in srgb, var(--error-color, #f44336) 10%, transparent);
  }
  .sc-tools-info {
    color: var(--secondary-text-color);
    background: var(--primary-background-color, #fafafa);
  }
  .sc-tools-editor::placeholder {
    color: var(--secondary-text-color, #727272);
    opacity: 1;
  }
  .sc-tools-help {
    margin-bottom: 12px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--sc-radius-sm);
    background: var(--card-background-color, #fff);
  }
  .sc-tools-help summary {
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 500;
    color: var(--primary-text-color);
    cursor: pointer;
    user-select: none;
  }
  .sc-tools-help summary:hover { color: var(--primary-color, #03a9f4); }
  .sc-tools-help-body {
    padding: 4px 16px 16px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  .sc-tools-help-body section { margin-top: 16px; }
  .sc-tools-help-body h4 {
    margin: 0 0 6px 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--primary-text-color);
  }
  .sc-tools-help-body p {
    margin: 0 0 8px 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--secondary-text-color);
  }
  .sc-tools-help-body code {
    font-family: var(--code-font-family, monospace);
    font-size: 12px;
    background: var(--primary-background-color, #fafafa);
    padding: 1px 4px;
    border-radius: 4px;
  }
  .sc-tools-help-body pre {
    margin: 0;
    padding: 12px 14px;
    overflow-x: auto;
    background: var(--code-editor-background-color, var(--card-background-color, #fff));
    border-radius: var(--sc-radius-sm);
  }
  .sc-tools-help-body pre code {
    background: none;
    padding: 0;
    color: var(--primary-text-color, #212121);
    font-size: 12px;
    line-height: 1.6;
    white-space: pre;
  }
`;
