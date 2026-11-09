import { defineConfig } from '@playwright/test'

// The built app in a real browser, the only place the map can be seen to
// work: jsdom has neither WebGL nor web workers. Left to itself the run
// serves frontend/dist; BASE_URL points it at a running copy instead, such
// as the Docker image or the hosted one.
const baseURL = process.env.BASE_URL || 'http://127.0.0.1:4173'

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0, // the tile server has its moments
  reporter: 'list',
  use: {
    baseURL,
    // Headless Chromium has no GPU to offer; this gives MapLibre WebGL in software.
    launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
  webServer: process.env.BASE_URL
    ? undefined
    : { command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort', url: baseURL, reuseExistingServer: !process.env.CI },
})
