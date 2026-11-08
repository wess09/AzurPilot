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
    material: 'glass',
    setMaterial: () => {},
    resolvedMode: 'light',
    customPalettes: [],
    saveCustomPalette: () => {},
    deleteCustomPalette: () => {},
    language: 'zh-CN',
    setLanguage: () => {},
  }
}

function render(theme: AppContextValue['theme'], material: AppContextValue['material'] = 'glass') {
  return renderToStaticMarkup(
    <AppContext.Provider value={{...createMockContext(theme), material}}>
      <InterfaceSettings />
    </AppContext.Provider>
  )
}

// 外观偏好在「界面设置」页；原先这些断言挂在系统设置页上（见 Settings.test.tsx）。
describe('界面设置页外观显示逻辑', () => {
  it('现代主题下显示当前主题，简约主题下显示配色和主题模式', () => {
    expect(render('legacy-light')).toContain('现代')
    const minimal = render('minimal')
    expect(minimal).toContain('简约')
    expect(minimal).toContain('主题模式')
    expect(minimal).toContain('配色方案')
    expect(minimal).not.toContain('自定义背景')
    expect(minimal).not.toContain('材质细节')
  })

  it('浅色与深色主题下均渲染材质与明暗分段控件', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme)
      expect(html).toContain('材质')
      expect(html).toContain('玻璃')
      expect(html).toContain('普通')
      expect(html).toContain('明暗')
      expect(html).toContain('浅色')
      expect(html).toContain('深色')
    }
  })

  it('渲染自定义背景，不渲染已废弃的独立配色方案与紧凑布局', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme)
      expect(html).toContain('自定义背景')
      expect(html).not.toContain('配色方案')
      expect(html).not.toContain('紧凑布局')
    }
  })
})

// 自定义外观：一级界面只有主题色与二级菜单入口；七个区域的滑块在二级菜单里。
describe('自定义外观块', () => {
  it('玻璃材质下渲染主题色与材质细节入口', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme, 'glass')
      expect(html, theme).toContain('主题色')
      expect(html, theme).toContain('材质细节')
      /* 滑块不再摊在一级界面：区域名与滑块都要等二级菜单打开才出现。 */
      expect(html, theme).not.toContain('一级面')
      expect(html, theme).not.toContain('type="range"')
    }
  })

  it('普通材质不给材质细节入口（没有材质层，调了看不见）', () => {
    const plain = render('legacy-light', 'plain')
    expect(plain).not.toContain('材质细节')
    expect(plain).toContain('主题色')
  })
})

describe('调度器位置偏好选项', () => {
  it('渲染调度器位置分段控件及左侧/右侧选项', () => {
    for (const theme of ['legacy-light', 'legacy-dark', 'minimal'] as const) {
      const html = render(theme)
      expect(html, theme).toContain('调度器位置')
      expect(html, theme).toContain('左侧')
      expect(html, theme).toContain('右侧')
    }
  })
})
