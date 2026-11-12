// @vitest-environment jsdom
/**
 * @fileoverview 总览页调度器排布的回归测试：左右位置、宽度记忆与拖拽调整。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Overview } from './Overview'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { getLayout, setLegacyRailWidth, resetLegacyRailWidth } from '../app/layout'
import { setSchedulerPosition } from '../app/schedulerPositionPrefs'

// jsdom 没实现 ResizeObserver，而页面挂载的子树会用到；这里给空实现，避免挂载即抛错。
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', MockResizeObserver)

// api 桩成最小快照：本组用例只测排布与拖拽，不关心后端数据。
vi.mock('../api/client', () => ({
  api: {
    request: vi.fn().mockResolvedValue({
      instance: 'test-instance',
      status: 'stopped',
      tasks: [],
      resources: [],
    }),
    onEvent: vi.fn().mockReturnValue(() => {}),
    subscribe: vi.fn().mockReturnValue(() => {}),
    getSnapshot: vi.fn().mockReturnValue('ready'),
  },
}))

// MonitorPanel 只桩不测：内容与本组用例无关，桩掉还能少渲染一整块。
vi.mock('../components/MonitorPanel', () => ({
  MonitorPanel: () => <div data-testid="monitor-panel">Monitor Panel</div>,
}))

function createMockContext(): AppContextValue {
  return {
    instancesLoaded: true,
    instances: [],
    refresh: async () => {},
    t: (key: string) => key,
    ui: (key, params) => translateUi('zh-CN', key, params),
    notify: () => {},
    previewEnabled: false,
    setPreviewEnabled: () => {},

    theme: 'legacy-light',
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

function renderOverview() {
  return render(
    <AppContext.Provider value={createMockContext()}>
      <MemoryRouter initialEntries={['/i/test-instance/overview']}>
        <Routes>
          <Route path="/i/:instance/overview" element={<Overview />} />
        </Routes>
      </MemoryRouter>
    </AppContext.Provider>
  )
}

describe('Overview 总览页调度器位置与排布', () => {
  beforeEach(() => {
    localStorage.clear()
    resetLegacyRailWidth()
    setSchedulerPosition('left')
  })

  afterEach(() => {
    cleanup()
    resetLegacyRailWidth()
    localStorage.clear()
  })

  it('默认排布在左侧，带有 rail-left 类名与 data-scheduler-position="left"', async () => {
    renderOverview()
    const grid = await screen.findByRole('heading', { name: 'test-instance' })
      .then(heading => heading.closest('.instance-page-grid'))

    expect(grid).not.toBeNull()
    expect(grid?.className).toContain('instance-page-grid')
    expect(grid?.className).toContain('rail-left')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('left')

    const handle = screen.getByRole('separator')
    expect(handle.getAttribute('data-side')).toBe('left')
  })

  it('切换到右侧时带有 rail-right 类名与 data-side="right"', async () => {
    setSchedulerPosition('right')
    renderOverview()
    const grid = await screen.findByRole('heading', { name: 'test-instance' })
      .then(heading => heading.closest('.instance-page-grid'))

    expect(grid).not.toBeNull()
    expect(grid?.className).toContain('instance-page-grid')
    expect(grid?.className).toContain('rail-right')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('right')

    const handle = screen.getByRole('separator')
    expect(handle.getAttribute('data-side')).toBe('right')
  })

  it('自定义宽度时传递 --legacy-rail-width 样式变量', async () => {
    setLegacyRailWidth(340)
    renderOverview()
    const grid = await screen.findByRole('heading', { name: 'test-instance' })
      .then(heading => heading.closest('.instance-page-grid'))

    expect(grid?.getAttribute('style')).toContain('--legacy-rail-width: 340px')
  })

  it('从 localStorage 恢复用户选择的右侧位置与宽度记忆', async () => {
    localStorage.setItem('azurpilot.layout.scheduler-position', 'right')
    setLegacyRailWidth(320)

    renderOverview()
    const grid = await screen.findByRole('heading', { name: 'test-instance' })
      .then(heading => heading.closest('.instance-page-grid'))

    expect(grid?.className).toContain('rail-right')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('right')
    expect(grid?.getAttribute('style')).toContain('--legacy-rail-width: 320px')
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('right')
    expect(localStorage.getItem('azurpilot.layout.legacy-rail-width')).toBe('320')
  })

  it('运行时动态切换调度器位置时即时响应排布变更', async () => {
    renderOverview()
    const getGrid = async () => {
      const heading = await screen.findByRole('heading', { name: 'test-instance' })
      return heading.closest('.instance-page-grid')
    }
    let grid = await getGrid()
    expect(grid?.className).toContain('rail-left')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('left')
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('left')

    await act(async () => {
      setSchedulerPosition('right')
    })
    grid = await getGrid()
    expect(grid?.className).toContain('rail-right')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('right')
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('right')

    await act(async () => {
      setSchedulerPosition('left')
    })
    grid = await getGrid()
    expect(grid?.className).toContain('rail-left')
    expect(grid?.getAttribute('data-scheduler-position')).toBe('left')
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('left')
  })

  it('调度器在右侧时可在总览页直接拖拽调整宽度并双击重置', async () => {
    setSchedulerPosition('right')
    setLegacyRailWidth(280)
    renderOverview()

    const handle = await screen.findByRole('separator')
    expect(handle.getAttribute('data-side')).toBe('right')

    // 把手在右侧：向左拖 50px 等于把栏加宽 50。
    fireEvent.pointerDown(handle, { button: 0, pointerId: 3, clientX: 600 })
    fireEvent.pointerMove(handle, { pointerId: 3, clientX: 550 })
    expect(getLayout().legacyRailWidth).toBe(330)
    fireEvent.pointerUp(handle, { pointerId: 3 })

    fireEvent.doubleClick(handle)
    expect(getLayout().legacyRailWidth).toBeNull()
  })
})
