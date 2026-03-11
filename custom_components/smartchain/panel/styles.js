export const SC_STYLES = `
  :host { display: block; }
  .sc-container {
    max-width: 960px;
    margin: 0 auto;
    padding: 16px;
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    color: var(--primary-text-color, #212121);
  }
  .sc-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
  }
  .sc-header h1 {
    margin: 0;
    font-size: 24px;
    font-weight: 400;
    color: var(--primary-text-color);
  }
  .sc-header ha-icon {
    color: var(--primary-color, #03a9f4);
    --mdc-icon-size: 32px;
  }
  .sc-tabs {
    display: flex;
    gap: 0;
    margin-bottom: 24px;
    border-bottom: 2px solid var(--divider-color, #e0e0e0);
  }
  .sc-tab {
    padding: 12px 24px;
    cursor: pointer;
    border: none;
    background: none;
    font-size: 14px;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: all 0.2s;
  }
  .sc-tab:hover { color: var(--primary-text-color); }
  .sc-tab.active {
    color: var(--primary-color, #03a9f4);
    border-bottom-color: var(--primary-color, #03a9f4);
  }
  .sc-card {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    padding: 24px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
    margin-bottom: 16px;
  }
  .sc-card h2 {
    margin: 0 0 8px 0;
    font-size: 18px;
    font-weight: 500;
  }
  .sc-card p {
    margin: 0 0 16px 0;
    color: var(--secondary-text-color);
    font-size: 14px;
  }
  .sc-textarea {
    width: 100%;
    min-height: 100px;
    padding: 12px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-family: inherit;
    font-size: 14px;
    resize: vertical;
    box-sizing: border-box;
  }
  .sc-textarea:focus {
    outline: none;
    border-color: var(--primary-color, #03a9f4);
  }
  .sc-select {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color);
    font-size: 14px;
    margin-bottom: 12px;
    box-sizing: border-box;
  }
  .sc-row { display: flex; gap: 12px; margin-bottom: 12px; }
  .sc-row > * { flex: 1; min-width: 0; }
  .sc-btn-row { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
  .sc-btn {
    padding: 10px 24px;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
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
  .sc-label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--secondary-text-color);
    margin-bottom: 6px;
  }
  .sc-hidden { display: none !important; }
  .sc-spinner {
    display: inline-block;
    width: 20px; height: 20px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: sc-spin 0.6s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }
  @keyframes sc-spin { to { transform: rotate(360deg); } }
  .sc-status {
    margin-top: 12px;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 14px;
  }
  .sc-status-success { background: var(--success-color, #4caf50); color: #fff; }
  .sc-status-error { background: var(--error-color, #f44336); color: #fff; }
  .sc-toggle-btn {
    background: none;
    border: none;
    color: var(--primary-color, #03a9f4);
    cursor: pointer;
    font-size: 12px;
    padding: 2px 6px;
    border-radius: 4px;
  }
  .sc-toggle-btn:hover { background: var(--primary-background-color, #f5f5f5); }
`;
