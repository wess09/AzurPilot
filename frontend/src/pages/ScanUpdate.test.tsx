// @vitest-environment jsdom
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import {translateUi} from '../i18n'
import {ScanUpdate} from './ScanUpdate'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
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
