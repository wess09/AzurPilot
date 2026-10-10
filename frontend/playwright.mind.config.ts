import {defineConfig} from '@playwright/test'
import config from './playwright.mock.config'

export default defineConfig({...config, testMatch: '**/mind-*.spec.ts'})
