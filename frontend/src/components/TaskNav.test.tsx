import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AppContext, type AppContextValue } from '../app/context'
import { TaskNav } from './TaskNav'
import { isDesktopDevice } from './TaskNavFlyout'
import type { Theme } from '../app/theme'
import type { Schema } from '../api/types'
import { translateUi } from '../i18n'

const mockSchema: Schema = {
  menu: {
    Alas: {
      menu: 'collapse',
      page: 'setting',
      tasks: ['Alas', 'General', 'Restart'],
    },
    Farm: {
      menu: 'collapse',
      page: 'setting',
      tasks: ['Main', 'Main2', 'ThreeOilLowCost'],
    },
  },
  args: {},
  translations: {},
}

const mockTranslations: Record<string, string> = {
  'Menu.Alas.name': '系统',
  'Menu.Farm.name': '出击Plus',
  'Task.Alas.name': '系统设置',
  'Task.General.name': '通用设置',
  'Task.Restart.name': '游戏重启',
  'Task.Main.name': '主线常规出击',
  'Task.Main2.name': '主线常规出击2',
  'Task.ThreeOilLowCost.name': '3油低耗出击',
}

function contextWith(theme: Theme): AppContextValue {
  return {
    instancesLoaded: true,
    instances: [{ name: 'default', status: 'stopped', serial: '127.0.0.1:5555', server: 'cn' }],
    schema: mockSchema,
    refresh: async () => {},
    t: (key: string) => mockTranslations[key] ?? key,
    ui: (key, params) => translateUi('zh-CN', key, params),
    notify: () => {},
    previewEnabled: false,
    setPreviewEnabled: () => {},
    devMode: false,
    setDevMode: () => {},
    theme,
    setTheme: () => {},
    colorMode: 'auto', resolvedMode: 'light', setColorMode: () => {},
    customPalettes: [], saveCustomPalette: () => {}, deleteCustomPalette: () => {},
    palette: 'ocean',
    setPalette: () => {},
    language: 'zh-CN',
    setLanguage: () => {},
  }
}

function render(path: string, props: {defaultOpenKey?: string} = {}, theme: Theme = 'legacy-light') {
  return renderToStaticMarkup(
    <AppContext.Provider value={contextWith(theme)}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/i/:instance/*" element={<TaskNav {...props} />} />
        </Routes>
      </MemoryRouter>
    </AppContext.Provider>
  )
}

describe('TaskNav 导航组件', () => {
  it('渲染一级分组按钮，未展开时不下发具体任务', () => {
    const html = render('/i/default/overview')

    expect(html).toContain('task-nav-container')
    expect(html).toContain('展开任务搜索')
    expect(html).not.toContain('搜索任务…')

    expect(html).toContain('task-group-button')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-controls="task-group-Alas"')
    expect(html).toContain('系统')
    expect(html).toContain('出击Plus')

    // 未展开的分组不渲染任务项，避免侧栏一上来就是长列表
    expect(html).not.toContain('task-submenu-list')
    expect(html).not.toContain('通用设置')
    // 一级菜单不展示任务数量，避免与展开箭头争夺视觉焦点
    expect(html).not.toContain('task-group-badge')
  })

  it('旧版主题展开分组后，具体任务往下列在侧栏里', () => {
    const html = render('/i/default/overview', {defaultOpenKey: 'Alas'})

    expect(html).toContain('task-group-button expanded')
    expect(html).toContain('aria-expanded="true"')

    expect(html).toContain('task-submenu-list')
    expect(html).toContain('task-submenu-item')
    expect(html).toContain('系统设置')
    expect(html).toContain('通用设置')
    expect(html).toContain('游戏重启')
    expect(html).toContain('href="/i/default/task/Alas"')
    expect(html).toContain('href="/i/default/task/General"')
    expect(html).toContain('href="/i/default/task/Restart"')

    // 旧版是树状内联列表，不再有浮出的二级面板
    expect(html).not.toContain('task-submenu-flyout')
    expect(html).not.toContain('aria-haspopup="menu"')
  })

  it('旧版主题处于某任务页时，所属分组自动展开并高亮', () => {
    const html = render('/i/default/task/Main')

    // Main 任务属于 Farm 分组（出击Plus）
    expect(html).toContain('task-group-button expanded active')
    expect(html).toContain('出击Plus')
    expect(html).toContain('href="/i/default/task/Main"')
  })

  it('其余主题继续用向右浮出的二级菜单', () => {
    const html = render('/i/default/overview', {defaultOpenKey: 'Alas'}, 'light')

    expect(html).toContain('aria-haspopup="menu"')
    expect(html).toContain('task-submenu-flyout')
    expect(html).toContain('href="/i/default/task/Alas"')
    // 浮出层不挂在侧栏的分组里，分组按钮也就不带 aria-controls
    expect(html).not.toContain('aria-controls="task-group-')
  })
})

describe('isDesktopDevice', () => {
  it('正确区分电脑端与移动端环境', () => {
    // node/SSR 环境下无 window，应安全回退为 false
    expect(isDesktopDevice()).toBe(false)

    const originalWindow = globalThis.window

    try {
      const mockWindow = {
        innerWidth: 1280,
        matchMedia: (query: string) => ({
          matches: query.includes('(hover: none)') ? false : true,
        }),
      }
      globalThis.window = mockWindow as unknown as Window & typeof globalThis

      // 电脑端：宽度 > 950 且支持 hover
      expect(isDesktopDevice()).toBe(true)

      // 移动端：宽度 <= 950
      mockWindow.innerWidth = 768
      expect(isDesktopDevice()).toBe(false)

      // 移动端触屏：宽度 > 950 但为 touch-only (hover: none)
      mockWindow.innerWidth = 1024
      mockWindow.matchMedia = (query: string) => ({
        matches: query.includes('(hover: none)') ? true : false,
      })
      expect(isDesktopDevice()).toBe(false)
    } finally {
      if (originalWindow === undefined) {
        delete (globalThis as { window?: unknown }).window
      } else {
        globalThis.window = originalWindow
      }
    }
  })
})
