import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { MockInstancePreview } from './MockInstancePreview'

// ui 用直通实现：渲染出的文案就是 i18n key 本身，断言按 key 匹配即可，不必引真实语言包。
const ui = ((key: string) => key) as never
const context = {
  ui,
  language: 'zh-CN',
  theme: 'light',
  navTo: vi.fn(),
  page: 'settings',
  setTheme: vi.fn(),
  notify: vi.fn(),
} as unknown as AppContextValue

describe('MockInstancePreview (全真模拟实例页预览)', () => {
  it('正确渲染全屏全真模拟实例页与材质调节检视器', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <MockInstancePreview onClose={vi.fn()} />
      </AppContext.Provider>,
    )

    expect(html).toContain('mock-instance-preview-overlay')
    expect(html).toContain('mock-preview-shell')
    expect(html).toContain('mock-preview-inspector')

    expect(html).toContain('breadcrumb')
    expect(html).toContain('connection-label')

    expect(html).toContain('settings.sampleModal')
    expect(html).toContain('settings.sampleMenu')

    expect(html).toContain('settings.inspectorTitle')
    expect(html).toContain('settings.closePreview')

    expect(html).toContain('settings.regionSurface')
    expect(html).toContain('settings.regionPlate')
    expect(html).toContain('settings.regionInset')
    expect(html).toContain('settings.regionControl')
    expect(html).toContain('settings.regionModal')
    expect(html).toContain('settings.regionMenu')
  })

  it('支持传入初始区域', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <MockInstancePreview onClose={vi.fn()} initialRegion="control" />
      </AppContext.Provider>,
    )
    expect(html).toContain('ui-knob-control.alpha')
  })

  it('在旧版主题下正确渲染 legacy 外壳与材质选单', () => {
    const legacyContext = {...context, theme: 'legacy-light'} as unknown as AppContextValue
    const html = renderToStaticMarkup(
      <AppContext.Provider value={legacyContext}>
        <MockInstancePreview onClose={vi.fn()} />
      </AppContext.Provider>,
    )
    expect(html).toContain('legacy-shell-preview')
    expect(html).toContain('settings.regionSurface')
    expect(html).toContain('settings.regionPlate')
    expect(html).toContain('settings.regionInset')
    expect(html).toContain('settings.regionControl')
    expect(html).toContain('settings.regionModal')
    expect(html).toContain('settings.regionMenu')
  })
})
