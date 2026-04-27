/**
 * SmartChain Panel — Design tokens & shared styles for the camera tab.
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

  .sc-camera-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 24px;
    font-family: var(--sc-font);
    color: var(--primary-text-color, #212121);
  }

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
`;
