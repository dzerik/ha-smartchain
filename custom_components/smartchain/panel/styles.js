/**
 * SmartChain Panel — Design tokens & shared styles.
 * Uses HA CSS custom properties for theme integration.
 */
export const SC_STYLES = `
  :host { display: block; }

  /* ========== CSS Custom Properties (Design Tokens) ========== */
  smartchain-panel {
    --sc-font: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    --sc-mono: 'Roboto Mono', 'Fira Code', 'Cascadia Code', monospace;
    --sc-radius-sm: 6px;
    --sc-radius-md: 10px;
    --sc-radius-lg: 14px;
    --sc-shadow: 0 2px 8px rgba(0,0,0,0.08);
    --sc-shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
    --sc-transition: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    --sc-sidebar-w: 280px;
  }

  /* ========== IDE Layout ========== */
  .sc-ide {
    display: flex;
    height: calc(100vh - 56px);
    font-family: var(--sc-font);
    color: var(--primary-text-color, #212121);
    overflow: hidden;
  }

  /* ========== Sidebar ========== */
  .sc-sidebar {
    width: var(--sc-sidebar-w);
    min-width: 220px;
    max-width: 400px;
    display: flex;
    flex-direction: column;
    background: var(--card-background-color, #fff);
    border-right: 1px solid var(--divider-color, #e0e0e0);
    overflow: hidden;
    transition: width var(--sc-transition), min-width var(--sc-transition);
  }
  .sc-sidebar.collapsed {
    width: 0;
    min-width: 0;
    border-right: none;
    overflow: hidden;
  }
  .sc-sidebar-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .sc-sidebar-header ha-icon {
    color: var(--primary-color, #03a9f4);
    --mdc-icon-size: 22px;
  }

  /* ========== Main Area ========== */
  .sc-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
  }

  /* ========== Mode Tabs (Editor / Camera) ========== */
  .sc-mode-tabs {
    display: flex;
    align-items: center;
    gap: 0;
    padding: 0 16px;
    background: var(--primary-background-color, #fafafa);
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    flex-shrink: 0;
  }
  .sc-mode-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 18px;
    cursor: pointer;
    border: none;
    background: none;
    font-size: 13px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: all var(--sc-transition);
  }
  .sc-mode-tab:hover { color: var(--primary-text-color); }
  .sc-mode-tab.active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }
  .sc-mode-tab ha-icon { --mdc-icon-size: 18px; }
  .sc-sidebar-toggle {
    background: none;
    border: none;
    color: var(--secondary-text-color, #727272);
    cursor: pointer;
    padding: 6px;
    border-radius: var(--sc-radius-sm);
    margin-right: 8px;
    transition: all var(--sc-transition);
  }
  .sc-sidebar-toggle:hover {
    background: var(--divider-color, #eee);
    color: var(--primary-text-color);
  }
  .sc-sidebar-toggle ha-icon { --mdc-icon-size: 20px; }

  /* ========== Editor Area ========== */
  .sc-editor-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 0;
  }

  /* ========== Status Bar ========== */
  .sc-statusbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 5px 16px;
    background: var(--primary-background-color, #fafafa);
    border-top: 1px solid var(--divider-color, #e0e0e0);
    font-size: 12px;
    color: var(--secondary-text-color, #888);
    flex-shrink: 0;
  }

  /* ========== Button System ========== */
  .sc-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 7px 16px;
    border: none;
    border-radius: var(--sc-radius-sm);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--sc-transition);
    white-space: nowrap;
    line-height: 1.4;
    font-family: inherit;
  }
  .sc-btn:disabled { opacity: 0.45; cursor: not-allowed; pointer-events: none; }
  .sc-btn ha-icon { --mdc-icon-size: 16px; }

  .sc-btn-primary {
    background: var(--primary-color, #03a9f4);
    color: #fff;
  }
  .sc-btn-primary:hover:not(:disabled) { filter: brightness(1.12); box-shadow: 0 2px 8px rgba(3,169,244,0.3); }

  .sc-btn-success {
    background: var(--success-color, #4caf50);
    color: #fff;
  }
  .sc-btn-success:hover:not(:disabled) { filter: brightness(1.1); box-shadow: 0 2px 8px rgba(76,175,80,0.3); }

  .sc-btn-outline {
    background: transparent;
    color: var(--primary-color, #03a9f4);
    border: 1px solid var(--primary-color, #03a9f4);
  }
  .sc-btn-outline:hover:not(:disabled) { background: color-mix(in srgb, var(--primary-color, #03a9f4) 10%, transparent); }

  .sc-btn-warn {
    background: var(--warning-color, #ff9800);
    color: #fff;
  }
  .sc-btn-warn:hover:not(:disabled) { filter: brightness(1.1); }

  .sc-btn-danger {
    background: var(--error-color, #f44336);
    color: #fff;
  }
  .sc-btn-danger:hover:not(:disabled) { filter: brightness(1.1); }

  .sc-btn-ghost {
    background: none;
    border: none;
    color: var(--secondary-text-color);
    padding: 6px 10px;
  }
  .sc-btn-ghost:hover:not(:disabled) {
    color: var(--primary-text-color);
    background: var(--divider-color, #eee);
  }

  .sc-btn-icon {
    background: none;
    border: none;
    color: var(--secondary-text-color);
    cursor: pointer;
    padding: 6px;
    border-radius: var(--sc-radius-sm);
    line-height: 1;
    transition: all var(--sc-transition);
  }
  .sc-btn-icon:hover:not(:disabled) { background: var(--divider-color, #eee); color: var(--primary-text-color); }
  .sc-btn-icon.active { color: var(--primary-color, #03a9f4); }
  .sc-btn-icon ha-icon { --mdc-icon-size: 20px; }

  /* ========== Spinner ========== */
  .sc-spinner {
    display: inline-block;
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: sc-spin 0.6s linear infinite;
    vertical-align: middle;
  }
  @keyframes sc-spin { to { transform: rotate(360deg); } }

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
  }
  .sc-toast {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 20px;
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
  .sc-toast-success { background: var(--success-color, #4caf50); color: #fff; }
  .sc-toast-error { background: var(--error-color, #f44336); color: #fff; }
  .sc-toast-info { background: var(--primary-color, #03a9f4); color: #fff; }
  .sc-toast-warning { background: var(--warning-color, #ff9800); color: #fff; }
  .sc-toast-out { animation: sc-toast-out 0.25s ease-in forwards; }
  @keyframes sc-toast-in { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
  @keyframes sc-toast-out { from { opacity: 1; } to { transform: translateY(10px); opacity: 0; } }

  /* ========== Confirm Dialog ========== */
  .sc-dialog-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: sc-fade-in 0.15s ease;
  }
  .sc-dialog {
    background: var(--card-background-color, #fff);
    border-radius: var(--sc-radius-lg);
    padding: 28px;
    max-width: 420px;
    width: 90%;
    box-shadow: var(--sc-shadow-lg);
    animation: sc-dialog-in 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .sc-dialog h3 { margin: 0 0 12px; font-size: 18px; font-weight: 600; color: var(--primary-text-color); }
  .sc-dialog p { margin: 0 0 24px; font-size: 14px; color: var(--secondary-text-color); line-height: 1.5; }
  .sc-dialog-actions { display: flex; justify-content: flex-end; gap: 10px; }
  @keyframes sc-fade-in { from { opacity: 0; } to { opacity: 1; } }
  @keyframes sc-dialog-in { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }

  .sc-hidden { display: none !important; }

  /* ========== Card (for camera tab) ========== */
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

  .sc-camera-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 24px;
  }

  /* ========== Responsive ========== */
  @media (max-width: 768px) {
    .sc-sidebar { position: absolute; z-index: 100; height: 100%; box-shadow: var(--sc-shadow-lg); }
    .sc-sidebar.collapsed { width: 0; }
    smartchain-panel { --sc-sidebar-w: 260px; }
  }
`;
