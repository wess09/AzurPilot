// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppContext, type AppContextValue } from '../app/context'
import type { Instance } from '../api/types'
import { ConfigManager } from './ConfigManager'
import { translateUi } from '../i18n'

// vi.mock 的工厂会被提升到 import 之前，模块级数据必须走 vi.hoisted。
const {request} = vi.hoisted(() => ({request: vi.fn()}))

vi.mock('../api/client', () => ({
  api: {
    request,
    // useConnection 用 useSyncExternalStore 订阅 api 快照：恒为 ready，订阅直接 no-op。
    subscribe: () => () => {},
    getSnapshot: () => 'ready',
  },
}))

// CreateInstance 挂在整只 ../app/App 上，拖家带口拖不动；本页单测用不到弹窗，桩成空组件。
vi.mock('../app/App', () => ({CreateInstance: () => null}))

const instances: Instance[] = [
  {name: 'asu-main', status: 'running', serial: '127.0.0.1:16384', server: 'MuMu12', region: 'cn', currentTask: 'Alas'},
  {name: 'asu-backup', status: 'stopped', serial: '127.0.0.1:16400', server: 'disabled'},
]

function mockContext(overrides?: Partial<AppContextValue>): AppContextValue {
  return {
    instancesLoaded: true,
    instances,
    refresh: vi.fn(async () => {}),
    t: (key: string) => key,
    ui: (key, params) => translateUi('zh-CN', key, params),
    notify: vi.fn(),
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
    ...overrides,
  }
}

function renderPage(overrides?: Partial<AppContextValue>) {
  // 卡片的「概览」是 react-router 的 Link，需要 Router 上下文才能渲染。
  return render(<MemoryRouter><AppContext.Provider value={mockContext(overrides)}><ConfigManager/></AppContext.Provider></MemoryRouter>)
}

afterEach(() => {
  cleanup()
  request.mockReset()
})

describe('配置管理页', () => {
  it('实例未加载完成时显示加载占位，不闪空态、不显示计数', () => {
    const {container} = renderPage({instancesLoaded: false, instances: []})
    expect(container.textContent).toContain(translateUi('zh-CN', 'common.loading'))
    expect(container.textContent).not.toContain(translateUi('zh-CN', 'config.empty'))
    expect(container.textContent).not.toContain('个实例')
  })

  it('页头计数摘要与实例数一致；卡片渲染名字、模拟器、serial 与当前任务', () => {
    const {container} = renderPage()
    expect(container.textContent).toContain('共 2 个实例')
    expect(container.textContent).toContain('asu-main')
    expect(container.textContent).toContain('Emulator.ServerName.MuMu12')
    expect(container.textContent).toContain(translateUi('zh-CN', 'common.notSet'))
    expect(container.textContent).toContain('127.0.0.1:16384')
    // currentTask 经 taskLabel 翻译；桩 t 原样返回键名，未知任务回落 Task.*.name。
    expect(container.textContent).toContain('Task.Alas.name')
    expect(container.textContent).toContain(translateUi('zh-CN', 'status.running'))
    expect(container.textContent).toContain(translateUi('zh-CN', 'status.stopped'))
  })

  it('删除走两击确认：第一击出现提示与确认按钮，第二击带 revision 调删除接口并刷新', async () => {
    request.mockImplementation((method: string) => method === 'config.get' ? {revision: 'r1'} : {})
    const refresh = vi.fn(async () => {})
    const {container} = renderPage({instances: instances.slice(0, 1), refresh})

    fireEvent.click(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.delete')}))
    expect(container.textContent).toContain('删除 asu-main？')
    expect(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.deleteConfirm')})).toBeTruthy()

    fireEvent.click(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.deleteConfirm')}))
    await waitFor(() => expect(request).toHaveBeenCalledWith('instances.delete', {instance: 'asu-main', revision: 'r1'}))
    expect(refresh).toHaveBeenCalled()
    expect(request).toHaveBeenCalledWith('config.get', {instance: 'asu-main'})
  })

  it('删除失败时错误进页面级 ErrorBox，确认态复位', async () => {
    request.mockImplementation((method: string) => {
      if (method === 'config.get') return {revision: 'r1'}
      throw new Error('disk full')
    })
    const {container} = renderPage({instances: instances.slice(0, 1)})
    fireEvent.click(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.delete')}))
    fireEvent.click(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.deleteConfirm')}))
    await waitFor(() => expect(container.textContent).toContain('disk full'))
    // 确认态复位：按钮回到「删除实例」。
    expect(screen.getByRole('button', {name: translateUi('zh-CN', 'instance.delete')})).toBeTruthy()
  })

  it('空列表显示空态，并在空态下方给出新建/导入快捷入口', () => {
    const {container} = renderPage({instances: []})
    expect(container.textContent).toContain(translateUi('zh-CN', 'config.empty'))
    // 页头与空态各一组新建/导入按钮。
    expect(screen.getAllByRole('button', {name: translateUi('zh-CN', 'config.create')})).toHaveLength(2)
    expect(screen.getAllByRole('button', {name: translateUi('zh-CN', 'config.import')})).toHaveLength(2)
  })
})
