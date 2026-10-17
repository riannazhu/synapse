import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e', fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5181', channel: 'chrome', viewport: { width: 1440, height: 1100 }, trace: 'retain-on-failure' },
  webServer: { command: 'npm run dev -- --port 5181 --strictPort', url: 'http://127.0.0.1:5181', reuseExistingServer: false },
});
