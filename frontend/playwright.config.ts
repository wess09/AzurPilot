import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // 股票与心智单元用例分别依赖专用 mock 服务，由对应的 Playwright 配置执行。
  testIgnore: ['**/mock.spec.ts', '**/stock-exchange/**', '**/mind-*.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60000,
  use: {baseURL: 'http://127.0.0.1:22391', headless: true, locale: 'zh-CN', viewport: {width: 1440, height: 1100}},
  webServer: {
    command: 'uv run python -m tests.serve_frontend',
    cwd: '..',
    url: 'http://127.0.0.1:22391/healthz',
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
})
