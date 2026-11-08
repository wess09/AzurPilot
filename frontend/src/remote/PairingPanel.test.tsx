import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { PairingPanel } from './PairingPanel'
import { translateUi } from '../i18n'

vi.mock('../api/client', () => ({
  api: {
    request: vi.fn().mockImplementation((method: string) => {
      if (method === 'remote.clients') {
        return Promise.resolve([
          { id: 'client-1', created_at: 1729214415 },
          { id: 'client-2', created_at: 1729214533 },
        ])
      }
      return Promise.resolve([])
    }),
  },
}))

function createMockContext(language: AppContextValue['language'] = 'zh-CN'): AppContextValue {
  return {
    instancesLoaded: true,
    instances: [],
    refresh: async () => {},
    t: (key: string) => key,
    ui: (key, params) => translateUi(language, key, params),
    notify: () => {},
    previewEnabled: false,
    setPreviewEnabled: () => {},
    devMode: false,
    setDevMode: () => {},
    theme: 'legacy-light',
    setTheme: () => {},
    material: 'glass',
    setMaterial: () => {},
    resolvedMode: 'light',
    customPalettes: [],
    saveCustomPalette: () => {},
    deleteCustomPalette: () => {},
    language,
    setLanguage: () => {},
  }
}

function render(ready: boolean, language: AppContextValue['language'] = 'zh-CN') {
  return renderToStaticMarkup(
    <AppContext.Provider value={createMockContext(language)}>
      <PairingPanel ready={ready} />
    </AppContext.Provider>,
  )
}

describe('PairingPanel 组件', () => {
  it('未就绪时禁用配对按钮并显示前置说明', () => {
    const html = render(false)
    expect(html).toContain('与 AzurPilot for Android 配对')
    expect(html).toContain('选择 cloudflare 模式并启用远程访问')
    expect(html).toContain('disabled=""')
    expect(html).not.toContain('pairing-qr')
  })

  it('就绪时按钮可用且不展示引导说明', () => {
    const html = render(true)
    expect(html).toContain('与 AzurPilot for Android 配对')
    expect(html).not.toContain('选择 cloudflare 模式并启用远程访问')
    expect(html).not.toContain('disabled=""')
    expect(html).toContain('配对')
  })

  it('支持不同语言渲染对应标题与按钮', () => {
    const enHtml = render(true, 'en-US')
    expect(enHtml).toContain('Pair with AzurPilot for Android')
    expect(enHtml).toContain('Pair')

    const jaHtml = render(true, 'ja-JP')
    expect(jaHtml).toContain('AzurPilot for Android とペアリング')

    const twHtml = render(false, 'zh-TW')
    expect(twHtml).toContain('與 AzurPilot for Android 配對')
    expect(twHtml).toContain('選擇 cloudflare 模式並啟用遠端存取')
  })

  it('已授权列表包含标题和空状态提示', () => {
    const html = render(false)
    expect(html).toContain('已授权的配对设备')
    expect(html).toContain('暂无已授权的设备')
  })
})
