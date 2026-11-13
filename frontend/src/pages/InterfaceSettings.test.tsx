import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { InterfaceSettings } from './InterfaceSettings'
import { translateUi } from '../i18n'

// renderToStaticMarkup 是服务端渲染路径，不会真正订阅外部 store；
// 把 useSyncExternalStore 替换成直接读快照，优先 getServerSnapshot。
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    useSyncExternalStore: (_subscribe: any, getSnapshot: any, getServerSnapshot?: any) => {
      return (getServerSnapshot ?? getSnapshot)()
    },
  }
})

// 桩掉 api 客户端：静态渲染不联网，订阅换空、快照给离线值、请求兜底返回空数据。
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

// 外观偏好的正向断言在本文件；Settings.test.tsx 断言系统设置页不再出现它们。
describe('界面设置页外观显示逻辑', () => {
  it('现代主题下显示当前主题，简约主题下显示主题模式', () => {
    // 主题家族下拉是 radix Select，选项文案不在静态标记里，这里只断言字段的可见标签。
    expect(render('legacy-light')).toContain('界面主题')
    const minimal = render('minimal')
    expect(minimal).toContain('界面主题')
    expect(minimal).toContain('主题模式')
    expect(minimal).not.toContain('自定义背景')
  })

  it('浅色与深色主题下均渲染材质与明暗字段', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme)
      // 材质/明暗改回下拉选择（与配置页同款 Select），选项文案在展开时才挂载，这里断言字段标签。
      expect(html).toContain('材质')
      expect(html).toContain('明暗')
    }
  })

  it('渲染自定义背景，不渲染已移除的调色板与紧凑布局', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme)
      expect(html).toContain('自定义背景')
      expect(html).not.toContain('配色方案')
      expect(html).not.toContain('紧凑布局')
    }
  })
})

// 自定义外观：主题色色卡与材质细节入口已整体移除。
describe('自定义外观块', () => {
  it('不再渲染主题色与材质细节入口', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      const html = render(theme, 'glass')
      expect(html, theme).not.toContain('主题色')
      expect(html, theme).not.toContain('材质细节')
      expect(html, theme).not.toContain('type="range"')
    }
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
