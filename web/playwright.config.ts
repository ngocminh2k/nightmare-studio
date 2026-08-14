import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:3001",
    browserName: "chromium",
    channel: "chrome",
    screenshot: "only-on-failure",
    trace: "on-first-retry"
  }
});
