export const SC_STYLES = `
  :host { display: block; }

  /* === IDE Layout === */
  .sc-ide {
    display: flex;
    height: calc(100vh - 56px);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    color: var(--primary-text-color, #212121);
    overflow: hidden;
  }

  /* --- Left sidebar --- */
  .sc-sidebar {
    width: 280px;
    min-width: 220px;
    max-width: 400px;
    display: flex;
    flex-direction: column;
    background: var(--card-background-color, #fff);
    border-right: 1px solid var(--divider-color, #e0e0e0);
    overflow: hidden;
  }
  .sc-sidebar-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    font-size: 15px;
    font-weight: 500;
  }
  .sc-sidebar-header ha-icon {
    color: var(--primary-color, #03a9f4);
    --mdc-icon-size: 22px;
  }

  /* --- Right main area --- */
  .sc-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
  }

  /* --- Toolbar --- */
  .sc-toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: var(--primary-background-color, #fafafa);
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .sc-toolbar-title {
    font-size: 13px;
    font-weight: 500;
    margin-right: auto;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--primary-text-color);
  }
  .sc-toolbar-dirty {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--warning-color, #ff9800);
    margin-left: 6px;
    flex-shrink: 0;
  }

  /* --- Mode tabs (Editor / Camera) --- */
  .sc-mode-tabs {
    display: flex;
    gap: 0;
    padding: 0 12px;
    background: var(--primary-background-color, #fafafa);
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    flex-shrink: 0;
  }
  .sc-mode-tab {
    padding: 8px 16px;
    cursor: pointer;
    border: none;
    background: none;
    font-size: 13px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: all 0.2s;
  }
  .sc-mode-tab:hover { color: var(--primary-text-color); }
  .sc-mode-tab.active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }

  /* --- Editor area --- */
  .sc-editor-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 0;
  }

  /* --- Status bar --- */
  .sc-statusbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 4px 12px;
    background: var(--primary-background-color, #fafafa);
    border-top: 1px solid var(--divider-color, #e0e0e0);
    font-size: 11px;
    color: var(--secondary-text-color, #888);
    flex-shrink: 0;
  }
  .sc-statusbar-ok { color: var(--success-color, #4caf50); }
  .sc-statusbar-err { color: var(--error-color, #f44336); }

  /* === Shared button styles === */
  .sc-btn {
    padding: 5px 12px;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }
  .sc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .sc-btn-primary {
    background: var(--primary-color, #03a9f4);
    color: #fff;
  }
  .sc-btn-primary:hover:not(:disabled) { filter: brightness(1.1); }
  .sc-btn-success {
    background: var(--success-color, #4caf50);
    color: #fff;
  }
  .sc-btn-success:hover:not(:disabled) { filter: brightness(1.1); }
  .sc-btn-outline {
    background: transparent;
    color: var(--primary-color, #03a9f4);
    border: 1px solid var(--primary-color, #03a9f4);
  }
  .sc-btn-outline:hover:not(:disabled) { background: var(--primary-color, #03a9f4); color: #fff; }
  .sc-btn-warn {
    background: var(--warning-color, #ff9800);
    color: #fff;
  }
  .sc-btn-warn:hover:not(:disabled) { filter: brightness(1.1); }
  .sc-btn-danger {
    background: var(--error-color, #f44336);
    color: #fff;
  }
  .sc-btn-ghost {
    background: none;
    border: none;
    color: var(--secondary-text-color);
    padding: 4px 8px;
    font-size: 12px;
  }
  .sc-btn-ghost:hover { color: var(--primary-text-color); background: var(--divider-color, #eee); }
  .sc-btn-icon {
    background: none;
    border: none;
    color: var(--secondary-text-color);
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
    line-height: 1;
  }
  .sc-btn-icon:hover { background: var(--divider-color, #eee); color: var(--primary-text-color); }
  .sc-btn-icon.active { color: var(--primary-color, #03a9f4); }

  .sc-spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: sc-spin 0.6s linear infinite;
    vertical-align: middle;
    margin-right: 6px;
  }
  @keyframes sc-spin { to { transform: rotate(360deg); } }

  .sc-hidden { display: none !important; }

  /* === Card (for camera tab) === */
  .sc-card {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    padding: 24px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
    margin-bottom: 16px;
  }
  .sc-card h2 { margin: 0 0 8px 0; font-size: 18px; font-weight: 500; }
  .sc-card p { margin: 0 0 16px 0; color: var(--secondary-text-color); font-size: 14px; }
  .sc-textarea {
    width: 100%;
    min-height: 60px;
    padding: 10px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-family: inherit;
    font-size: 13px;
    resize: vertical;
    box-sizing: border-box;
  }
  .sc-textarea:focus { outline: none; border-color: var(--primary-color, #03a9f4); }
  .sc-select {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 6px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-size: 13px;
    box-sizing: border-box;
  }
  .sc-row { display: flex; gap: 10px; }
  .sc-row > * { flex: 1; min-width: 0; }
  .sc-label {
    display: block;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--secondary-text-color);
    margin-bottom: 4px;
  }
  .sc-camera-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 16px;
  }
`;
