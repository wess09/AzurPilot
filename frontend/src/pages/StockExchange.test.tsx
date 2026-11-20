// @vitest-environment jsdom
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {MemoryRouter, Route, Routes} from 'react-router-dom'
import {expect, it, vi} from 'vitest'
import {StockExchange} from './StockExchange'
import {stockText} from '../i18n.stock'

const mocks = vi.hoisted(() => ({request: vi.fn(), onEvent: vi.fn()}))
vi.mock('../api/client', () => ({api: mocks}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({language: 'zh-CN', ui: (key: string) => key})}))

vi.stubGlobal('ResizeObserver', class {observe() {} unobserve() {} disconnect() {}})

it('keeps registration after an older status read and ignores automatic reads during the write', async () => {
  const t = stockText['zh-CN']
  const old = {registered: false, bound: false, deleted: false, bindingCode: '', stock: null, message: ''}
  const registered = {...old, registered: true, bindingCode: 'new-code'}
  let completeOld!: (value: typeof old) => void, completeWrite!: (value: typeof registered) => void
  let onEvent!: (event: {topic: string; data: {instance: string}}) => void
  mocks.onEvent.mockImplementation((fn) => {onEvent = fn; return () => {}})
  mocks.request.mockResolvedValueOnce(old).mockReturnValueOnce(new Promise(resolve => {completeOld = resolve})).mockReturnValueOnce(new Promise(resolve => {completeWrite = resolve}))
  render(<MemoryRouter initialEntries={['/i/demo/stock']}><Routes><Route path="/i/:instance/stock" element={<StockExchange/>}/></Routes></MemoryRouter>)
  await screen.findByRole('heading', {name: t.registerTitle})
  act(() => onEvent({topic: 'stock', data: {instance: 'demo'}}))
  fireEvent.change(screen.getByLabelText(t.username), {target: {value: 'test'}})
  fireEvent.click(screen.getByRole('checkbox', {name: t.consent}))
  fireEvent.click(screen.getByRole('button', {name: t.register}))
  act(() => onEvent({topic: 'stock', data: {instance: 'demo'}}))
  expect(mocks.request).toHaveBeenCalledTimes(3)
  await act(async () => completeWrite(registered))
  await screen.findByText('绑定股票 new-code')
  await act(async () => completeOld(old))
  await waitFor(() => expect(screen.getByText('绑定股票 new-code')).toBeTruthy())
  expect(mocks.request).toHaveBeenCalledTimes(3)
})
