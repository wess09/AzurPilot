// @vitest-environment jsdom
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {MemoryRouter, Route, Routes} from 'react-router-dom'
import {api} from '../api/client'
import {translateUi} from '../i18n'
import {FleetAnalysis} from './FleetAnalysis'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({ui: (key: Parameters<typeof translateUi>[1]) => translateUi('zh-CN', key), instances: [], notify: vi.fn()})}))
// 四个子页全部换成带标记的桩：断言只看「哪个标记挂在文档里」，子页自身的渲染不在本文件职责内。
vi.mock('./MindCalculator', () => ({MindCalculator: () => <p>mind content</p>}))
vi.mock('./FleetTechnology', () => ({FleetTechnology: () => <p>technology content</p>}))
vi.mock('./FleetLedger', () => ({FleetLedger: () => <p>data content</p>}))
vi.mock('./ScanUpdate', () => ({ScanUpdate: () => <p>scan content</p>}))
const tabs = ['data', 'technology', 'mind', 'scan'] as const
function page(tab: string) {
  return render(<MemoryRouter initialEntries={[`/i/test/task/FleetAnalysis${tab ? `?tab=${tab}` : ''}`]}><Routes><Route path="/i/:instance/task/FleetAnalysis" element={<FleetAnalysis/>}/></Routes></MemoryRouter>)
}
// api.request 默认挂起：未显式 mock 的用例页面应停在加载态，防止跑进后续分支。
beforeEach(() => {localStorage.clear(); vi.mocked(api.request).mockReset().mockReturnValue(new Promise(() => {}))})
afterEach(() => {cleanup(); vi.useRealTimers()})

describe('ship data navigation', () => {
  it.each(tabs)('mounts only the active %s page and requests its dock snapshot', tab => {
    page(tab)
    expect(screen.getAllByRole('tab')).toHaveLength(4)
    expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['舰队科技', '养成计算', '扫描更新', '我的舰船'])
    const panel = screen.getByRole('tabpanel')
    expect(panel.textContent).toBe(`${tab} content`)
    const selected = screen.getByRole('tab', {selected: true})
    expect(panel.getAttribute('aria-labelledby')).toBe(selected.id)
    for (const other of tabs.filter(value => value !== tab)) expect(screen.queryByText(`${other} content`)).toBeNull()
    expect(api.request).toHaveBeenCalledExactlyOnceWith('dock.report', {instance: 'test'})
  })

  it('switches tabs on click and unmounts the previous page', () => {
    page('data')
    fireEvent.mouseDown(screen.getByRole('tab', {name: translateUi('zh-CN', 'analysis.scanPage')}), {button: 0})
    expect(screen.getByRole('tabpanel').textContent).toBe('scan content')
    expect(screen.queryByText('data content')).toBeNull()
    expect(screen.getByRole('tab', {selected: true}).textContent).toBe(translateUi('zh-CN', 'analysis.scanPage'))
    expect(api.request).toHaveBeenCalledTimes(1)
  })

  it('renders dock load failures from the request effect', async () => {
    vi.mocked(api.request).mockRejectedValueOnce(new Error('dock unavailable'))
    page('data')
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('dock unavailable'))
  })

  it('restores the last page but still honors an explicit tab link', () => {
    const first = page('mind')
    first.unmount()
    const second = page('')
    expect(screen.getByRole('tabpanel').textContent).toBe('mind content')
    second.unmount()
    page('data')
    expect(screen.getByRole('tabpanel').textContent).toBe('data content')
  })

  it('only reloads the snapshot on request instead of polling', async () => {
    vi.useFakeTimers()
    vi.mocked(api.request).mockResolvedValue({} as never)
    page('data')
    await act(async () => {vi.advanceTimersByTime(15000)})
    expect(api.request).toHaveBeenCalledExactlyOnceWith('dock.report', {instance: 'test'})
    await act(async () => fireEvent.click(screen.getByRole('button', {name: translateUi('zh-CN', 'mind.reload')})))
    expect(api.request).toHaveBeenCalledTimes(2)
  })
})
