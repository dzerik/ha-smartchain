import { defineConfig } from "vitest/config";

/**
 * The panel is plain ES modules served straight to the browser: no bundler, no
 * transpile step, no npm dependency at runtime. Vitest is here to *load* those
 * same files, not to change how they are written — so there is no plugin, no
 * alias and no transform configured below. If a test ever needs one, the panel
 * has drifted away from being browser-loadable and that is the bug.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["custom_components/smartchain/panel/**/*.test.js"],
    // The panel's own sources must never be collected as tests, and nothing
    // outside the panel is JavaScript at all.
    globals: false,
  },
});
