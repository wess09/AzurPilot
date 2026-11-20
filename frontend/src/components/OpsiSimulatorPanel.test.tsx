// @vitest-environment jsdom
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import type {OpsiSimulatorStatus} from '../api/types'
import {OpsiSimulatorPanel} from './OpsiSimulatorPanel'

const request = vi.hoisted(() => vi.fn())
vi.mock('../api/client', () => ({api: {request}}))
vi.mock('../app/context', () => ({useConnection: () => 'ready', useApp: () => ({ui: (key: string) => key, t: (key: string) => key, language: 'en'})}))
vi.mock('./LogPanel', () => ({LogPanel: () => <div>logs</div>}))

function status(runId: number, running: boolean, cursor: number): OpsiSimulatorStatus {
  return {instance: 'a', state: running ? 'running' : 'idle', running, completedSamples: 0, totalSamples: 0, error: '', runId, result: null, figure: null, logs: {instance: 'a', cursor, reset: false, entries: []}}
}

afterEach(() => {cleanup(); request.mockReset()})

it('ignores an old in-flight poll after starting, including its log cursor', async () => {
  let release!: (value: OpsiSimulatorStatus) => void
  const delayed = new Promise<OpsiSimulatorStatus>(resolve => {release = resolve})
  request.mockImplementation((method: string) => {
    if (method === 'opsi.simulator.start') return Promise.resolve(status(2, true, 3))
    if (method === 'opsi.simulator.status') return request.mock.calls.filter(([name]) => name === method).length === 1 ? Promise.resolve(status(1, false, 3)) : delayed
    throw new Error(method)
  })
  const {container} = render(<OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>)
  await screen.findByRole('button', {name: 'simulator.start'})
  await waitFor(() => expect(request.mock.calls.filter(([name]) => name === 'opsi.simulator.status').length).toBeGreaterThanOrEqual(2), {timeout: 2000})
  fireEvent.click(screen.getByRole('button', {name: 'simulator.start'}))
  await waitFor(() => expect(container.querySelector('.opsi-simulator-panel')?.getAttribute('data-run-id')).toBe('2'))
  await act(async () => release(status(1, false, 999)))
  expect(container.querySelector('.opsi-simulator-panel')?.getAttribute('data-run-id')).toBe('2')
  const statusCalls = request.mock.calls.filter(([name]) => name === 'opsi.simulator.status')
  expect(statusCalls.at(-1)?.[1].after).toBe(3)
})
