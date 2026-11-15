// @vitest-environment jsdom
/**
 * @fileoverview 扫描更新页的导入导出测试：清单与截图分别走 mind.import/mind.recognize，导出失败时不下载、不改已保存数据。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import {translateUi} from '../i18n'
import {ScanUpdate} from './ScanUpdate'

// api 整体 mock：用例只关心请求参数与回调时序，不连真实后端。
vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
// vi.mock 的工厂执行早于本模块体，connection 必须用 vi.hoisted 声明才能在工厂里引用；用例改 value 模拟断线。
const connection = vi.hoisted(() => ({value: 'ready'}))
vi.mock('../app/context', () => ({useConnection: () => connection.value, useApp: () => ({
  ui: (key: Parameters<typeof translateUi>[1]) => translateUi('zh-CN', key), instances: [], notify: vi.fn(),
})}))

const report: DockReport = {instance: 'test', revision: 'r1', updated_at: '', min_level: 1, max_level: 125,
  ships: [], complete: false, review_count: 0, source: 'empty', pending_revision: null, pending_changes: []}
const onReport = vi.fn(), onBusy = vi.fn()
function page(value: DockReport | undefined, locked = false) {
  return render(<ScanUpdate instance="test" report={value} locked={locked} onReport={onReport} onBusy={onBusy}/>)
}
beforeEach(() => {
  localStorage.clear(); connection.value = 'ready'; vi.clearAllMocks()
  vi.mocked(api.request).mockReset()
})
afterEach(() => {cleanup(); vi.restoreAllMocks()})

describe('ship imports', () => {
  it.each([
    {label: '导入舰船清单', accept: '.json,.csv,.xlsx', filename: 'ships.json', method: 'mind.import'},
    {label: '导入船坞截图', accept: 'image/*', filename: 'dock.png', method: 'mind.recognize'},
  ])('opens and stages $label', async ({label, accept, filename, method}) => {
    const view = page(report)
    const input = view.container.querySelector<HTMLInputElement>(`input[type="file"][accept="${accept}"]`)!
    // 桩掉 input.click：jsdom 打不开文件选择框，这里只断言「点击确实触发了打开」。
    const click = vi.spyOn(input, 'click').mockImplementation(() => {})
    vi.mocked(api.request).mockResolvedValueOnce({ships: []} as never).mockResolvedValueOnce(report)
    const button = screen.getByRole<HTMLButtonElement>('button', {name: label})
    expect(button.dataset.slot).toBe('button')
    fireEvent.click(button)
    expect(click).toHaveBeenCalledOnce()
    fireEvent.change(input, {target: {files: [new File(['test'], filename)]}})
    await waitFor(() => expect(onReport).toHaveBeenCalledExactlyOnceWith(report))
    expect(api.request).toHaveBeenNthCalledWith(1, method, {instance: 'test', filename, content: 'dGVzdA=='})
    expect(api.request).toHaveBeenNthCalledWith(2, 'dock.stageImport', {instance: 'test', revision: 'r1', ships: []})
    expect(onBusy.mock.calls).toEqual([[true], [false]])
  })

  it('disables both import buttons while data is unavailable, locked, or pending review', () => {
    const view = page(undefined)
    const buttons = () => ['导入舰船清单', '导入船坞截图'].map(name => screen.getByRole<HTMLButtonElement>('button', {name}))
    expect(buttons().every(button => button.disabled)).toBe(true)
    view.rerender(<ScanUpdate instance="test" report={report} locked onReport={onReport} onBusy={onBusy}/>)
    expect(buttons().every(button => button.disabled)).toBe(true)
    const pending = {...report, pending_changes: [{id: 'pending', operation: 'add', kind: 'ship', ship_id: null, group_type: null, name: '', before: null, after: null, fields: [], candidates: []}] as DockReport['pending_changes']}
    view.rerender(<ScanUpdate instance="test" report={pending} locked={false} onReport={onReport} onBusy={onBusy}/>)
    expect(buttons().every(button => button.disabled)).toBe(true)
  })
})

describe('ship JSON export', () => {
  it('disables export before data loads, while locked, and while disconnected', () => {
    const view = page(undefined)
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '导出舰船 JSON'}).disabled).toBe(true)
    view.rerender(<ScanUpdate instance="test" report={report} locked onReport={onReport} onBusy={onBusy}/>)
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '导出舰船 JSON'}).disabled).toBe(true)
    connection.value = 'closed'
    view.rerender(<ScanUpdate instance="test" report={report} locked={false} onReport={onReport} onBusy={onBusy}/>)
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '导出舰船 JSON'}).disabled).toBe(true)
    expect(api.request).not.toHaveBeenCalled()
  })

  it('reports a failed refresh without downloading or changing saved data', async () => {
    // 桩掉 a.click：导出成功会真触发下载，本用例要断言失败路径从未调用它。
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.mocked(api.request).mockRejectedValueOnce(new Error('export unavailable'))
    page(report)
    fireEvent.click(screen.getByRole('button', {name: '导出舰船 JSON'}))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('export unavailable'))
    expect(api.request).toHaveBeenCalledExactlyOnceWith('dock.report', {instance: 'test'})
    expect(click).not.toHaveBeenCalled()
    expect(onReport).not.toHaveBeenCalled()
    expect(onBusy.mock.calls).toEqual([[true], [false]])
  })
})
