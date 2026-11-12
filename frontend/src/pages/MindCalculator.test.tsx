// @vitest-environment jsdom
import {afterEach, beforeEach, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react'
import {MemoryRouter, Route, Routes} from 'react-router-dom'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import type {Catalog, Report} from '../fleet-tech/types'
import {translateUi} from '../i18n'
import type {CultivationReport} from '../mind/cultivation'
import {MindCalculator} from './MindCalculator'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({language: 'zh-CN',
  ui: (key: Parameters<typeof translateUi>[1], params: Parameters<typeof translateUi>[2]) => translateUi('zh-CN', key, params)})}))
const dock: DockReport = {instance: 'test', revision: 'r1', updated_at: null, min_level: 1, max_level: 125,
  complete: false, review_count: 0, source: 'manual', pending_revision: null, pending_changes: [],
  ships: ['企业', '埃塞克斯', '杜威'].map((name, index) => ({id: index + 1, group_type: index + 100,
    name, level: 100, rarity: 'SSR', base_rarity: 'SSR', extra_exp: null, review: false, source: 'manual'}))}
const catalog: Catalog = {updated_at: '', source_commit: '', max_points: 0, nation_points: {}, nations: {},
  ships: dock.ships.map(card => ({group_type: card.group_type!, name: card.name, names: {}, code: card.id,
    handbook_type: 0, blueprint: false, full_star_rule: 'ordinary_level_cap', nationality: 1,
    rarity: 'SSR', type: card.id === 3 ? 1 : 7, technology: {pt_get: 1, pt_upgrage: 1, pt_level: 1,
      max_star: 5, add_get_shiptype: [7], add_get_attr: 5, add_get_value: 1,
      add_level_shiptype: [7], add_level_attr: 5, add_level_value: 1}}))}
const technology: Report = {instance: 'test', revision: 't1', data_version: 'r1', ships: [],
  nation_levels: {}, bonuses: {}, ship_bonuses: {}, nation_bonuses: {}, confirmed_points: 0,
  completed: 0, milestone_counts: {owned: 0, full_star: 0, lv120: 0}}
const costs: CultivationReport = {instance: 'test', revision: 'r1', target_level: 120, included: 3,
  unknown: 0, mind: 600, mind2: 0, gold: 6000, rules_sha256: 'rules', mind_costs_100_to_120: {SSR: 2200},
  ships: dock.ships.map(card => ({id: card.id, name: card.name, current_level: card.level, level: card.level,
    target_level: 120, mind: card.id * 100, mind2: 0, gold: card.id * 1000, status: 'exact', notes: [], stages: []}))}
const isChecked = (element: HTMLElement) => element.getAttribute('aria-checked') === 'true'
const all = () => screen.getByRole<HTMLInputElement>('checkbox', {name: '全选当前筛选'})
const ship = (name: string) => screen.getByRole<HTMLInputElement>('checkbox', {name: `参与计算 ${name}`})
const search = (value: string) => fireEvent.change(screen.getByRole('searchbox'), {target: {value}})
async function show() {
  render(<MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<MindCalculator report={dock}/>}/></Routes></MemoryRouter>)
  await screen.findByRole('table')
}
beforeEach(() => {
  localStorage.clear()
  vi.mocked(api.request).mockReset().mockImplementation(async method => {
    if (method === 'fleetTech.catalog') return catalog
    if (method === 'fleetTech.report') return technology
    if (method === 'mind.plan') return costs
    throw new Error(`Unexpected method: ${method}`)
  })
})
afterEach(cleanup)

it('starts selected, follows individual choices, and toggles all visible ships together', async () => {
  await show()
  expect(isChecked(all())).toBe(true)
  expect(all().closest('th')?.textContent).toContain('参与计算')
  fireEvent.click(ship('企业'))
  expect(isChecked(all())).toBe(false)
  expect(isChecked(ship('杜威'))).toBe(true)
  fireEvent.click(all())
  expect(isChecked(all())).toBe(true)
  expect(isChecked(ship('企业'))).toBe(true)
  fireEvent.click(all())
  for (const name of ['企业', '埃塞克斯', '杜威']) expect(isChecked(ship(name))).toBe(false)
  expect(screen.getByText('计入 0 种舰船', {exact: false})).toBeTruthy()
})

it('clears all ships from a filtered view and only selects ships matching the current filters', async () => {
  await show()
  fireEvent.click(screen.getAllByRole('button', {name: '航母'})[0])
  expect(screen.queryByRole('checkbox', {name: '参与计算 杜威'})).toBeNull()
  fireEvent.click(all())
  expect(isChecked(ship('企业'))).toBe(false)
  expect(isChecked(ship('埃塞克斯'))).toBe(false)
  expect(screen.getByText('计入 0 种舰船', {exact: false})).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', {name: '全部'})[0])
  expect(isChecked(ship('杜威'))).toBe(false)
  fireEvent.click(screen.getAllByRole('button', {name: '航母'})[0])
  search('企业')
  fireEvent.click(all())
  expect(isChecked(all())).toBe(true)
  search('')
  expect(isChecked(all())).toBe(false)
  expect(isChecked(ship('埃塞克斯'))).toBe(false)
  search('不存在')
  expect(all().disabled).toBe(true)
  expect(isChecked(all())).toBe(false)
  expect(screen.getByText('计入 1 种舰船', {exact: false})).toBeTruthy()
})

it('respects saved exclusions and the included-only filter', async () => {
  localStorage.setItem('azurpilot.cultivation-auto.test', JSON.stringify({excluded_groups: [100]}))
  await show()
  expect(isChecked(all())).toBe(false)
  fireEvent.click(screen.getByRole('checkbox', {name: '仅显示参与计算'}))
  expect(isChecked(all())).toBe(true)
  fireEvent.click(all())
  expect(all().disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox', {name: '仅显示参与计算'}))
  for (const name of ['企业', '埃塞克斯', '杜威']) expect(isChecked(ship(name))).toBe(false)
})

it('retains costs for excluded ships from initial load and updates totals without recalculating', async () => {
  localStorage.setItem('azurpilot.cultivation-auto.test', JSON.stringify({excluded_groups: [100]}))
  await show()
  const row = within(ship('企业').closest('tr')!)
  expect(row.getAllByText('100')).toHaveLength(2)
  expect(row.getByText('1,000')).toBeTruthy()
  const totalValues = () => [...document.querySelectorAll('.cultivation-totals strong')].map(el => el.textContent)
  expect(totalValues()).toEqual(['500', '5,000'])
  fireEvent.click(ship('埃塞克斯'))
  expect(within(ship('埃塞克斯').closest('tr')!).getByText('2,000')).toBeTruthy()
  expect(totalValues()).toEqual(['300', '3,000'])
  fireEvent.click(all())
  expect(totalValues()).toEqual(['600', '6,000'])
  fireEvent.click(all())
  expect(totalValues()).toEqual(['0', '0'])
  expect(row.getByText('1,000')).toBeTruthy()
  expect(vi.mocked(api.request).mock.calls.filter(([method]) => method === 'mind.plan')).toEqual([
    ['mind.plan', {instance: 'test', revision: 'r1', ship_ids: [1, 2, 3], target_level: 120}],
  ])
})

it('recalculates costs after the dock revision changes while preserving exclusions', async () => {
  let updated = false
  vi.mocked(api.request).mockImplementation(async method => {
    if (method === 'fleetTech.catalog') return catalog
    if (method === 'fleetTech.report') return updated ? {...technology, revision: 't2', data_version: 'r2'} : technology
    if (method === 'mind.plan') return updated ? {...costs, revision: 'r2',
      ships: costs.ships.map(row => ({...row, mind: row.mind! + 50, gold: row.gold! + 500}))} : costs
    throw new Error(`Unexpected method: ${method}`)
  })
  const view = (report: DockReport) => <MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<MindCalculator report={report}/>}/></Routes></MemoryRouter>
  const rendered = render(view(dock))
  await screen.findByRole('table')
  fireEvent.click(ship('企业'))
  updated = true
  rendered.rerender(view({...dock, revision: 'r2'}))
  await within(ship('企业').closest('tr')!).findByText('1,500')
  expect(isChecked(ship('企业'))).toBe(false)
  expect([...document.querySelectorAll('.cultivation-totals strong')].map(el => el.textContent)).toEqual(['600', '6,000'])
  expect(vi.mocked(api.request).mock.calls.filter(([method]) => method === 'mind.plan')).toHaveLength(2)
})

it('excludes unknown costs from totals and keeps unknown counts scoped to selected ships', async () => {
  // 直接改模块级夹具做 unknown 场景，finally 里还原，避免泄漏到其他用例。
  costs.ships[0] = {...costs.ships[0], status: 'unknown', mind: null, gold: null}
  try {
    await show()
    expect(screen.getByText('计入 2 种舰船', {exact: false}).textContent).toContain('信息不足 1 种')
    expect([...document.querySelectorAll('.cultivation-totals strong')].map(el => el.textContent)).toEqual(['500', '5,000'])
    fireEvent.click(ship('企业'))
    expect(screen.getByText('计入 2 种舰船', {exact: false}).textContent).not.toContain('信息不足')
    expect([...document.querySelectorAll('.cultivation-totals strong')].map(el => el.textContent)).toEqual(['500', '5,000'])
  } finally {costs.ships[0] = {...costs.ships[0], status: 'exact', mind: 100, gold: 1000}}
})
