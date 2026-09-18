import { defineConfig, devices } from "@playwright/test";

// End-to-end tests hit a REAL frontend + API pair. Both servers must be up
// (docker compose, or `npm run dev` plus uvicorn locally). `webServer` below
// can start them for local runs when E2E_AUTO_START=1.
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./src/e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Needed when running inside a container without a sandbox namespace.
        launchOptions: { args: ["--no-sandbox", "--disable-dev-shm-usage"] },
      },
    },
  ],
  webServer: process.env.E2E_AUTO_START
    ? [
        {
          command: "python3 -m uvicorn app.main:app --port 8000",
          cwd: "../backend",
          url: "http://127.0.0.1:8000/health",
          reuseExistingServer: true,
          timeout: 30_000,
        },
        {
          command: "npm run build && npm run preview",
          url: "http://127.0.0.1:4173",
          reuseExistingServer: true,
          timeout: 60_000,
        },
      ]
    : undefined,
});
