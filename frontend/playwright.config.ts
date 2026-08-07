import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const python = existsSync("../.venv/bin/python") ? ".venv/bin/python" : "python";
const databaseUrlEnvironmentName = "CVA_DATABASE_URL";
const databaseUrl =
  process.env.CVA_E2E_DATABASE_URL ??
  `sqlite+pysqlite:////tmp/cva-stage1-playwright-${process.pid}.db`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn comprehension_verification.web.app:app --host 127.0.0.1 --port 8000 --no-access-log`,
      cwd: "..",
      env: {
        ...process.env,
        CVA_ENVIRONMENT: "test",
        [databaseUrlEnvironmentName]: databaseUrl,
        CVA_AUTH_MODE: "local",
        CVA_OBJECT_STORE_MODE: "memory",
        CVA_JOB_RUNNER_MODE: "inline",
        CVA_MODEL_MODE: "mock",
        CVA_P10_ENABLED: "false",
        CVA_SESSION_SECRET: "not-a-secret-playwright-session-key-32-bytes",
        CVA_LOCAL_INVITED_EMAILS: "teacher@example.test",
      },
      url: "http://127.0.0.1:8000/api/readiness",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: ".",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
