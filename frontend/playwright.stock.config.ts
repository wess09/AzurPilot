import {defineConfig} from '@playwright/test'

export default defineConfig({
  testDir:'./e2e/stock-exchange',workers:1,reporter:'list',timeout:60000,
  use:{baseURL:'http://127.0.0.1:5176',headless:true,locale:'zh-CN',viewport:{width:1600,height:1080}},
  webServer:[
    {command:'npm run mock',env:{AZURPILOT_MOCK_PORT:'22592'},url:'http://127.0.0.1:22592/healthz',reuseExistingServer:false},
    {command:'npm run dev -- --mode mock --port 5176',env:{AZURPILOT_MOCK_PORT:'22592'},url:'http://127.0.0.1:5176',reuseExistingServer:false},
  ],
})
