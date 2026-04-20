const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 2 * 60 * 1000,
  expect: { timeout: 5000 },
  retries: 1,
  use: {
    baseURL: 'http://127.0.0.1:8081',
    headless: true,
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
  },
  reporter: [['html', { outputFolder: 'playwright-report' }]],
});
