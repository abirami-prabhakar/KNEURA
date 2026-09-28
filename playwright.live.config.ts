import { defineConfig } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { resolve } from 'node:path'

process.env.KNEURA_LIVE_DATA ||= resolve('.kneura', `live-test-${randomUUID()}`)
process.env.KNEURA_DATA_DIR = process.env.KNEURA_LIVE_DATA
process.env.KNEURA_LIVE_PASSWORD ||= randomUUID()

export default defineConfig({
  testDir: './tests/live', outputDir: 'test-results/live', workers: 1, timeout: 180000,
  expect: { timeout: 15000 },
  use: { baseURL: 'http://127.0.0.1:5179', channel: process.env.PLAYWRIGHT_CHANNEL || undefined, trace: 'retain-on-failure' },
  webServer: [
    { command: 'python tests/live_server.py', url: 'http://127.0.0.1:8011/api/health', timeout: 90000,
      env: { KNEURA_ORIGINS: 'http://127.0.0.1:5179', KNEURA_LLM_URL: process.env.KNEURA_LIVE_LLM === '1' ? process.env.KNEURA_LLM_URL || '' : '', KNEURA_SECURE_COOKIE: '0' } },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5179 --strictPort', url: 'http://127.0.0.1:5179', env: { KNEURA_API_PROXY: 'http://127.0.0.1:8011' } },
  ],
})
