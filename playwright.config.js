const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 60000,
  workers: 1,
  use: { browserName: 'chromium', headless: true, viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
});
