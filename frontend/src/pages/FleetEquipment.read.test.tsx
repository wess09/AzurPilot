// @vitest-environment jsdom
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {MemoryRouter, Route, Routes} from 'react-router-dom'
import {api} from '../api/client'
import {translateUi} from '../i18n'
import {FleetEquipment} from './FleetEquipment'

const state = vi.hoisted(() => ({connection: 'ready', code: '', patches: 0}))
vi.mock('../api/client', () => ({api: {request: vi.fn(async (method: string, params?: {changes?: {path: string; value: unknown; expected?: unknown}[]}) => {
  if (method === 'config.patch') {
    state.patches++
    const codes = params?.changes?.find(change => change.path.endsWith('.Codes'))
    if (codes?.expected !== JSON.stringify({DD: [state.code]})) throw Object.assign(new Error('conflict'), {code: 'CONFLICT'})
    state.code = JSON.parse(codes.value as string).DD[0]
  }
  return {revision: 1, values: {FleetInfo: {FleetEquipment: {Enabled: false, Codes: JSON.stringify({DD: [state.code]}), State: {}}}}}
})}}))
vi.mock('../config/editors', () => ({editor: () => ({settled: async () => {}})}))
vi.mock('../app/context', () => ({useConnection: () => state.connection, useApp: () => ({ui: (key: Parameters<typeof translateUi>[1]) => translateUi('zh-CN', key), notify: vi.fn()})}))

const view = () => <MemoryRouter initialEntries={['/i/test/equipment']}><Routes><Route path="/i/:instance/equipment" element={<FleetEquipment/>}/></Routes></MemoryRouter>
const input = () => screen.getByRole('textbox', {name: '驱逐舰 装备码 1'}) as HTMLInputElement
beforeEach(() => {state.connection = 'ready'; state.code = 'original'; state.patches = 0; vi.mocked(api.request).mockClear()})
afterEach(cleanup)

describe('fleet equipment reads', () => {
  it('rehydrates a clean form after reconnect', async () => {
    const page = render(view())
    await waitFor(() => expect(input().value).toBe('original'))
    state.connection = 'disconnected'; page.rerender(view())
    state.code = 'external'
    state.connection = 'ready'; page.rerender(view())
    await waitFor(() => expect(input().value).toBe('external'))
  })

  it('preserves a draft and refuses an external conflict until the user reloads', async () => {
    const page = render(view())
    await waitFor(() => expect(input().value).toBe('original'))
    fireEvent.change(input(), {target: {value: 'draft'}})
    state.connection = 'disconnected'; page.rerender(view())
    state.code = 'external'
    state.connection = 'ready'; page.rerender(view())
    await waitFor(() => expect(vi.mocked(api.request).mock.calls.filter(call => call[0] === 'config.get').length).toBeGreaterThanOrEqual(2))
    expect(input().value).toBe('draft')
    fireEvent.click(screen.getByRole('button', {name: '保存装备码'}))
    await screen.findByText(/配置已在其他位置更改/)
    expect(state.patches).toBe(1)
    expect(input().value).toBe('draft')
    fireEvent.click(screen.getByRole('button', {name: '放弃草稿并重新加载'}))
    await waitFor(() => expect(input().value).toBe('external'))
  })
})
