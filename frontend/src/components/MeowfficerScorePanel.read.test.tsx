// @vitest-environment jsdom
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import type {MeowfficerScoreReport} from '../api/types'
import {MeowfficerScorePanel} from './MeowfficerScorePanel'

const request = vi.hoisted(() => vi.fn())
vi.mock('../api/client', () => ({api: {request}, ApiError: class ApiError extends Error {code = ''}}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({ui: (key: string) => key})}))
vi.mock('./ui', async importOriginal => {
  const original = await importOriginal<typeof import('./ui')>()
  return {...original, Modal: ({children}: {children: React.ReactNode}) => <div role="dialog">{children}</div>}
})

const report: MeowfficerScoreReport = {instance: 'a', generatedAt: 'now', count: 1, cats: [{cat: 'Old Cat', talents: [], rubrics: []}]}
afterEach(() => {cleanup(); request.mockReset()})

it('does not restore a stale report after a clear completes', async () => {
  let release!: (value: MeowfficerScoreReport) => void
  const delayed = new Promise<MeowfficerScoreReport>(resolve => {release = resolve})
  request.mockImplementation((method: string) => {
    if (method === 'meowfficer.clearReport') return Promise.resolve({})
    if (method === 'meowfficer.scoreReport') return request.mock.calls.filter(([name]) => name === method).length === 1 ? Promise.resolve(report) : delayed
    throw new Error(method)
  })
  render(<MeowfficerScorePanel instance="a"/>)
  await screen.findByText('Old Cat')
  fireEvent.click(screen.getByRole('button', {name: 'meow.refresh'}))
  await waitFor(() => expect(request.mock.calls.filter(([name]) => name === 'meowfficer.scoreReport').length).toBe(2))
  fireEvent.click(screen.getByRole('button', {name: 'meow.clear'}))
  fireEvent.click(screen.getByRole('button', {name: 'meow.clearConfirm'}))
  await screen.findByText('meow.emptyTitle')
  await act(async () => release(report))
  expect(screen.queryByText('Old Cat')).toBeNull()
  expect(screen.getByText('meow.emptyTitle')).toBeTruthy()
})
