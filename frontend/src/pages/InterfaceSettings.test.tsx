import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { InterfaceSettings } from './InterfaceSettings'
import { translateUi } from '../i18n'

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    useSyncExternalStore: (_subscribe: any, getSnapshot: any, getServerSnapshot?: any) => {
      return (getServerSnapshot ?? getSnapshot)()
    },
  }
})

vi.mock('../api/client', () => ({
  api: {
    subscribe: () => () => {},
    getSnapshot: () => 'disconnected',
    request: vi.fn().mockResolvedValue({ groups: [], notice: '', demo: false }),
  },
}))

function createMockContext(theme: AppContextValue['theme']): AppContextValue {
  return {
    instancesLoaded: true,
    instances: [],
    refresh: async () => {},
    t: (key: string) => key,
    ui: (key, params) => translateUi('zh-CN', key, params),
    notify: () => {},
    previewEnabled: false,
    setPreviewEnabled: () => {},
    devMode: false,
    setDevMode: () => {},
    theme,
    setTheme: () => {},
    palette: 'ocean',
    setPalette: () => {},
    colorMode: 'auto',
    resolvedMode: 'light',
    setColorMode: () => {},
    customPalettes: [],
    saveCustomPalette: () => {},
    deleteCustomPalette: () => {},
    language: 'zh-CN',
    setLanguage: () => {},
  }
}

function render(theme: AppContextValue['theme']) {
  return renderToStaticMarkup(
    <AppContext.Provider value={createMockContext(theme)}>
      <InterfaceSettings />
    </AppContext.Provider>
  )
}

// 外观偏好在「界面设置」页；原先这些断言挂在系统设置页上（见 Settings.test.tsx）。
describe('界面设置页自定义背景显示逻辑', () => {
  it('浅色主题下渲染自定义背景，不渲染简约配色方案', () => {
    const html = render('light')
    expect(html).toContain('自定义背景')
    expect(html).not.toContain('配色方案')
  })

  it('深色主题下渲染自定义背景，不渲染简约配色方案', () => {
    const html = render('dark')
    expect(html).toContain('自定义背景')
    expect(html).not.toContain('配色方案')
  })

  it('简约主题下不渲染自定义背景，仅渲染简约配色方案', () => {
    const html = render('minimal')
    expect(html).not.toContain('自定义背景')
    expect(html).toContain('配色方案')
  })

  it('旧版浅色/深色不渲染自定义背景，也没有换配色概念', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme)
      expect(html).not.toContain('自定义背景')
      expect(html).not.toContain('配色方案')
    }
  })

  it('主题下拉列出全部五个主题', () => {
    const html = render('light')
    for (const label of ['浅色', '深色', '简约', '旧版·浅色', '旧版·深色']) {
      expect(html).toContain(label)
    }
  })
})
