// @vitest-environment jsdom
import {afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi} from 'vitest'
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import type {MindCatalog} from '../mind/types'
import {translateUi} from '../i18n'
import {FleetLedger} from './FleetLedger'
import {ScanUpdate, safeScanChanges} from './ScanUpdate'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({language: 'zh-CN', ui: (key: Parameters<typeof translateUi>[1]) => translateUi('zh-CN', key), instances: [], notify: vi.fn()})}))
const report: DockReport = {instance: 'test', revision: 'r1', updated_at: null, min_level: 1, max_level: 125, complete: false, review_count: 0, source: 'manual', pending_revision: 'p1', pending_changes: [], ships: [1, 2].map(id => ({id, name: '重复舰船', group_type: 100, level: 120, rarity: 'SSR', base_rarity: 'SSR', extra_exp: null, review: false, source: 'manual'}))}
const catalog: MindCatalog = {updated_at: '', ships: [{name: '重复舰船', group_type: 100, rarity: 'SSR', base_rarity: 'SSR', base_name: '重复舰船', group: '', type: '驱逐', nationality: 1}]}
function ledger(value: DockReport | undefined, entry = '?tab=data') {
  return render(<MemoryRouter initialEntries={[entry]}><FleetLedger instance="test" report={value} onReport={vi.fn()} onBusy={vi.fn()}/></MemoryRouter>)
}
// jsdom 没实现 scrollIntoView；页面聚焦深链行时会调用它，这里只桩不验证。
beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', {configurable: true, value: vi.fn()})
})
afterAll(() => {
  delete (Element.prototype as {scrollIntoView?: Element['scrollIntoView']}).scrollIntoView
})
beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  // 默认让 api.request 挂起：未显式 mock 的用例页面应停在加载态，防止跑进后续分支。
  vi.mocked(api.request).mockReset().mockReturnValue(new Promise(() => {}))
})
afterEach(cleanup)

describe('current ships and scan separation', () => {
  it('loads the catalog before showing confirmed ships and editing controls', async () => {
    let resolve!: (value: MindCatalog) => void
    vi.mocked(api.request).mockReturnValueOnce(new Promise<MindCatalog>(done => {resolve = done}))
    ledger(report)
    expect(screen.getByRole('status').textContent).toContain(translateUi('zh-CN', 'common.loading'))
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByRole('button', {name: '保存'})).toBeNull()
    expect(api.request).toHaveBeenCalledExactlyOnceWith('mind.catalog', {instance: 'test'})
    await act(async () => resolve(catalog))
    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getAllByRole('combobox', {name: /舰名 · 重复舰船 #/})).toHaveLength(2)
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '保存'}).disabled).toBe(true)
    expect(screen.queryByRole('heading', {name: '待确认差异'})).toBeNull()
  })

  it('keeps the duplicate deep link while report data loads and highlights its exact copy', async () => {
    vi.mocked(api.request).mockResolvedValueOnce(catalog)
    const view = ledger(undefined, '?tab=data&ship=2')
    await waitFor(() => expect(api.request).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('status').textContent).toContain(translateUi('zh-CN', 'common.loading'))
    expect(screen.queryByRole('table')).toBeNull()
    view.rerender(<MemoryRouter initialEntries={['?tab=data&ship=2']}><FleetLedger instance="test" report={report} onReport={vi.fn()} onBusy={vi.fn()}/></MemoryRouter>)
    const second = await screen.findByRole('combobox', {name: '舰名 · 重复舰船 #2'})
    expect(second.closest('tr')?.classList.contains('ledger-highlight')).toBe(true)
    expect(screen.getByRole('combobox', {name: '舰名 · 重复舰船 #1'}).closest('tr')?.classList.contains('ledger-highlight')).toBe(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('accepts only additions and updates in the safe batch', async () => {
    const changes = (['add', 'update', 'remove', 'resolve'] as const).map(operation => ({id: operation, operation, kind: 'ship' as const, ship_id: null, group_type: 100, name: '重复舰船', before: null, after: {level: 120}, fields: ['level'], candidates: report.ships}))
    expect(safeScanChanges(changes).map(item => item.operation)).toEqual(['add', 'update'])
    const onReport = vi.fn(), onBusy = vi.fn()
    vi.mocked(api.request).mockResolvedValueOnce(report)
    render(<ScanUpdate instance="test" report={{...report, pending_changes: changes}} locked={false} onReport={onReport} onBusy={onBusy}/>)
    const target = screen.getByRole('combobox', {name: '目标卡片 resolve'})
    expect(target.textContent).toContain('选择目标')
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '接受 resolve'}).disabled).toBe(true)
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '扫描船坞'}).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', {name: /确认无歧义的新增和更新/}))
    await waitFor(() => expect(onReport).toHaveBeenCalledExactlyOnceWith(report))
    expect(api.request).toHaveBeenCalledExactlyOnceWith('dock.review', {instance: 'test', revision: 'r1', pending_revision: 'p1', decisions: [{id: 'add', accept: true}, {id: 'update', accept: true}]})
    expect(onBusy.mock.calls).toEqual([[true], [false]])
  })

  it('saves an inline edit for the selected physical copy without editing its duplicate', async () => {
    const onReport = vi.fn(), onBusy = vi.fn()
    const updated = {...report, revision: 'r2', ships: report.ships.map(ship => ship.id === 2 ? {...ship, level: 121} : ship)}
    vi.mocked(api.request).mockResolvedValueOnce(catalog).mockResolvedValueOnce(updated)
    render(<MemoryRouter><FleetLedger instance="test" report={report} onReport={onReport} onBusy={onBusy}/></MemoryRouter>)
    const second = await screen.findByRole<HTMLInputElement>('spinbutton', {name: '等级 · 重复舰船 #2'})
    fireEvent.change(second, {target: {value: '121'}})
    expect(screen.getByRole<HTMLInputElement>('spinbutton', {name: '等级 · 重复舰船 #1'}).value).toBe('120')
    fireEvent.click(screen.getByRole('button', {name: '保存'}))
    await waitFor(() => expect(onReport).toHaveBeenCalledExactlyOnceWith(updated))
    expect(api.request).toHaveBeenLastCalledWith('dock.patch', {instance: 'test', revision: 'r1', changes: [{
      id: 2, name: '重复舰船', group_type: 100, level: 121, rarity: 'SSR', base_rarity: 'SSR',
      full_star: null, form: null, review: false,
    }]})
    expect(onBusy.mock.calls).toEqual([[true], [false]])
    expect(screen.getByText(translateUi('zh-CN', 'analysis.saved'))).toBeTruthy()
    await waitFor(() => expect(sessionStorage.getItem('azurpilot.fleet-ledger.v1.test')).toBeNull())
  })

  it('shows the highest copy per identity without merging unknown or different identities', async () => {
    vi.mocked(api.request).mockResolvedValue(catalog)
    const ships = [
      {...report.ships[0]!, level: 100}, {...report.ships[1]!, level: 120},
      {...report.ships[0]!, id: 3, group_type: 200},
      {...report.ships[0]!, id: 4, group_type: null, review: true},
      {...report.ships[0]!, id: 5, group_type: null, review: true},
    ]
    ledger({...report, ships})
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', {name: '去重后舰船'}))
    expect(screen.getAllByRole('spinbutton', {name: /等级 · 重复舰船 #/})).toHaveLength(4)
    expect(screen.queryByRole('spinbutton', {name: '等级 · 重复舰船 #1'})).toBeNull()
    expect(screen.getByRole('spinbutton', {name: '等级 · 重复舰船 #2'})).toBeTruthy()
    expect(api.request).toHaveBeenCalledExactlyOnceWith('mind.catalog', {instance: 'test'})
    fireEvent.click(screen.getByRole('button', {name: '去重后舰船'}))
    expect(screen.getAllByRole('spinbutton', {name: /等级 · 重复舰船 #/})).toHaveLength(5)
  })

  it('lets an unresolved same-name ship choose its faction and then save the review', async () => {
    const candidates = [{...catalog.ships[0]!, name: '约克（皇家）', raw_name: '约克', group_type: 20307, type: '重巡', nationality: 2, code: 125},
      {...catalog.ships[0]!, name: '约克（铁血）', raw_name: '约克', group_type: 40311, type: '重巡', nationality: 4, code: 546}]
    vi.mocked(api.request).mockResolvedValueOnce({...catalog, ships: candidates}).mockResolvedValueOnce(report)
    ledger({...report, ships: [{...report.ships[0]!, name: '约克', group_type: null, review: true}]})
    const checkbox = await screen.findByRole('checkbox', {name: '需要核对 · 约克 #1'})
    expect(checkbox.hasAttribute('disabled')).toBe(false)
    fireEvent.click(checkbox)
    await waitFor(() => expect(checkbox.getAttribute('aria-checked')).toBe('true'))
    expect(screen.getByRole('alert').textContent).toContain('请先在舰名下选择')
    const identity = screen.getByRole('combobox', {name: '确认舰船身份 · 约克 #1'})
    fireEvent.keyDown(identity, {key: 'ArrowDown'})
    const texts = (await screen.findAllByRole('option')).map(option => option.textContent ?? '')
    expect(texts.some(text => text.includes('皇家'))).toBe(true)
    expect(texts.some(text => text.includes('铁血'))).toBe(true)
    fireEvent.keyDown(identity, {key: 'Escape'})
    expect(api.request).toHaveBeenCalledTimes(1)
  })

  it('can confirm a unique normalized name by clicking its review checkbox', async () => {
    vi.mocked(api.request).mockResolvedValueOnce({...catalog, ships: [{...catalog.ships[0]!, name: '北安普敦Ⅱ', raw_name: '北安普敦Ⅱ'}]})
    ledger({...report, ships: [{...report.ships[0]!, name: '北安普敦II', group_type: null, review: true}]})
    const checkbox = await screen.findByRole('checkbox', {name: '需要核对 · 北安普敦II #1'})
    fireEvent.click(checkbox)
    expect(screen.getByRole('checkbox', {name: '需要核对 · 北安普敦Ⅱ #1'}).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByRole<HTMLButtonElement>('button', {name: '保存'}).disabled).toBe(false)
    expect(api.request).toHaveBeenCalledTimes(1)
  })

  it('restores filters, search, level range and sorting when the page is reopened', async () => {
    vi.mocked(api.request).mockResolvedValue(catalog)
    const first = ledger(report)
    await screen.findByRole('table')
    fireEvent.change(screen.getByRole('searchbox'), {target: {value: '重复'}})
    fireEvent.change(screen.getByLabelText('最低等级'), {target: {value: '100'}})
    fireEvent.click(screen.getByRole('button', {name: '去重后舰船'}))
    fireEvent.click(screen.getByRole('button', {name: '等级'}))
    first.unmount()
    ledger(report)
    await screen.findByRole('table')
    expect(screen.getByRole<HTMLInputElement>('searchbox').value).toBe('重复')
    expect(screen.getByLabelText<HTMLInputElement>('最低等级').value).toBe('100')
    expect(screen.getByRole('button', {name: '去重后舰船'}).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('columnheader', {name: '等级'}).getAttribute('aria-sort')).toBe('descending')
    expect(screen.getAllByRole('spinbutton', {name: /等级 · 重复舰船 #/})).toHaveLength(1)
  })

  it('keeps an explicit copy link visible despite remembered filters and deduplication', async () => {
    localStorage.setItem('azurpilot.fleet-view.v1.test.ledger.query', JSON.stringify('其他舰船'))
    localStorage.setItem('azurpilot.fleet-view.v1.test.ledger.filters', JSON.stringify({records: ['unique']}))
    vi.mocked(api.request).mockResolvedValueOnce(catalog)
    ledger({...report, ships: [{...report.ships[0]!, level: 125}, {...report.ships[1]!, level: 100}]}, '?tab=data&ship=2')
    const target = await screen.findByRole('spinbutton', {name: '等级 · 重复舰船 #2'})
    expect(target.closest('tr')?.classList.contains('ledger-highlight')).toBe(true)
    expect(screen.getByRole<HTMLInputElement>('searchbox').value).toBe('其他舰船')
  })
})
