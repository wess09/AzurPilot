// @vitest-environment jsdom
import {afterEach, expect, it, vi} from 'vitest'
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {MemoryRouter, Route, Routes} from 'react-router-dom'
import {api} from '../api/client'
import type {Catalog, Report} from '../fleet-tech/types'
import {translateFleetTech} from '../fleet-tech/i18n'
import {translateUi} from '../i18n'
import {FleetTechnology} from './FleetTechnology'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
const connection = vi.hoisted(() => ({value: 'ready'}))
vi.mock('../app/context', () => ({useConnection: () => connection.value, useApp: () => ({language: 'en-US', ui: (key: Parameters<typeof translateUi>[1]) => translateUi('en-US', key), notify: vi.fn()})}))
const catalog: Catalog = {updated_at: '', source_commit: '', max_points: 0, nation_points: {}, nations: {}, ships: []}
const report: Report = {instance: 'test', revision: 'a', data_version: '', ships: [], nation_levels: {}, bonuses: {}, ship_bonuses: {}, nation_bonuses: {}, confirmed_points: 0, completed: 0, milestone_counts: {owned: 0, full_star: 0, lv120: 0}}
function deferred<T>() {let resolve!: (value: T) => void; const promise = new Promise<T>(yes => {resolve = yes}); return {promise, resolve}}
afterEach(() => {cleanup(); localStorage.clear(); sessionStorage.clear(); connection.value = 'ready'})

it('loads catalog and report in parallel, caches catalog, and prevents an older refresh overwriting a write', async () => {
  const oldRead = deferred<Report>(), write = deferred<Report>()
  let reads = 0
  vi.mocked(api.request).mockReset().mockImplementation(async method => {
    if (method === 'fleetTech.catalog') return catalog
    if (method === 'fleetTech.report') return ++reads === 1 ? report : oldRead.promise
    if (method === 'fleetTech.mergeShips') return write.promise
    throw new Error(`Unexpected method: ${method}`)
  })
  const reloadRef: {current: (() => void) | undefined} = {current: undefined}, onBusy = vi.fn()
  render(<MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<FleetTechnology reloadRef={reloadRef} busy={false} onBusy={onBusy}/>}/></Routes></MemoryRouter>)
  expect(vi.mocked(api.request).mock.calls.map(([method]) => method)).toEqual(['fleetTech.catalog', 'fleetTech.report'])
  await screen.findByRole('table')
  act(() => reloadRef.current?.())
  expect(vi.mocked(api.request).mock.calls.filter(([method]) => method === 'fleetTech.catalog')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', {name: translateFleetTech('en-US', 'mergeShips')}))
  await act(async () => write.resolve({...report, revision: 'written'}))
  await act(async () => oldRead.resolve({...report, revision: 'obsolete'}))
  fireEvent.click(screen.getByRole('button', {name: translateFleetTech('en-US', 'mergeShips')}))
  await waitFor(() => expect(vi.mocked(api.request).mock.calls.filter(([method]) => method === 'fleetTech.mergeShips')[1]?.[1]).toMatchObject({revision: 'written'}))
})

it('ignores repeated reloads while a report refresh is pending', async () => {
  const refresh = deferred<Report>()
  let reportReads = 0
  vi.mocked(api.request).mockReset().mockImplementation(async method => {
    if (method === 'fleetTech.catalog') return catalog
    if (method === 'fleetTech.report') return ++reportReads === 1 ? report : refresh.promise
    throw new Error(`Unexpected method: ${method}`)
  })
  const reloadRef: {current: (() => void) | undefined} = {current: undefined}, onBusy = vi.fn()
  render(<MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<FleetTechnology reloadRef={reloadRef} busy={false} onBusy={onBusy}/>}/></Routes></MemoryRouter>)
  await screen.findByRole('table')
  act(() => reloadRef.current?.())
  act(() => {reloadRef.current?.(); reloadRef.current?.()})
  await act(async () => refresh.resolve(report))
  expect(reportReads).toBe(2)
  expect(vi.mocked(api.request).mock.calls.filter(([method]) => method === 'fleetTech.catalog')).toHaveLength(1)
})

it('waits for both reads to settle before offering retry for a failed catalog', async () => {
  const initialReport = deferred<Report>()
  let catalogReads = 0, reportReads = 0
  vi.mocked(api.request).mockReset().mockImplementation(async method => {
    if (method === 'fleetTech.catalog') {if (++catalogReads === 1) throw new Error('catalog failed'); return catalog}
    if (method === 'fleetTech.report') return ++reportReads === 1 ? initialReport.promise : report
    throw new Error(`Unexpected method: ${method}`)
  })
  const reloadRef: {current: (() => void) | undefined} = {current: undefined}, onBusy = vi.fn()
  render(<MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<FleetTechnology reloadRef={reloadRef} busy={false} onBusy={onBusy}/>}/></Routes></MemoryRouter>)
  await act(async () => {})
  expect(screen.queryByText('catalog failed')).toBeNull()
  expect(screen.queryByRole('button', {name: 'Retry'})).toBeNull()
  await act(async () => initialReport.resolve(report))
  await screen.findByText('catalog failed')
  fireEvent.click(screen.getByRole('button', {name: 'Retry'}))
  await screen.findByRole('table')
  expect(catalogReads).toBe(2)
  expect(reportReads).toBe(2)
})

it('retries a failed catalog refresh even when cached catalog data exists', async () => {
  let catalogReads = 0
  vi.mocked(api.request).mockReset().mockImplementation(async method => {
    if (method === 'fleetTech.catalog') {if (++catalogReads === 2) throw new Error('catalog failed'); return catalog}
    if (method === 'fleetTech.report') return report
    throw new Error(`Unexpected method: ${method}`)
  })
  const reloadRef: {current: (() => void) | undefined} = {current: undefined}, onBusy = vi.fn()
  const view = () => <MemoryRouter initialEntries={['/test']}><Routes><Route path="/:instance" element={<FleetTechnology reloadRef={reloadRef} busy={false} onBusy={onBusy}/>}/></Routes></MemoryRouter>
  const rendered = render(view())
  await screen.findByRole('table')
  connection.value = 'offline'; rendered.rerender(view())
  connection.value = 'ready'; rendered.rerender(view())
  await screen.findByText('catalog failed')
  fireEvent.click(screen.getByRole('button', {name: 'Retry'}))
  await waitFor(() => expect(screen.queryByText('catalog failed')).toBeNull())
  expect(catalogReads).toBe(3)
})
