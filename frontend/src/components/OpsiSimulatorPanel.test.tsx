// @vitest-environment jsdom
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import type {OpsiSimulatorStatus} from '../api/types'
import {OpsiSimulatorPanel} from './OpsiSimulatorPanel'

const request = vi.hoisted(() => vi.fn())
const connection = vi.hoisted(() => ({value: 'ready'}))
vi.mock('../api/client', () => ({api: {request}}))
vi.mock('../app/context', () => ({useConnection: () => connection.value, useApp: () => ({ui: (key: string) => key, t: (key: string) => key, language: 'en'})}))
vi.mock('./LogPanel', () => ({LogPanel: ({logs}: {logs: OpsiSimulatorStatus['logs'] | null}) => <div>{logs?.entries.map(entry => entry.text).join(',')}</div>}))

function status(runId: number, running: boolean, cursor: number): OpsiSimulatorStatus {
  return {instance: 'a', state: running ? 'running' : 'idle', running, completedSamples: 0, totalSamples: 0, error: '', runId, result: null, figure: null, logs: {instance: 'a', cursor, reset: false, entries: []}}
}

afterEach(() => {cleanup(); request.mockReset(); connection.value = 'ready'})

it('reconnects from the last accepted cursor after a cancelled poll resolves', async () => {
  let release!: (value: OpsiSimulatorStatus) => void
  const delayed = new Promise<OpsiSimulatorStatus>(resolve => {release = resolve})
  request.mockImplementation((method: string) => {
    if (method !== 'opsi.simulator.status') throw new Error(method)
    const count = request.mock.calls.filter(([name]) => name === method).length
    return count === 1 ? Promise.resolve(status(4, false, 7)) : count === 2 ? delayed : Promise.resolve(status(4, false, 8))
  })
  const panel = <OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>
  const {rerender} = render(panel)
  await screen.findByRole('button', {name: 'simulator.start'})
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2), {timeout: 2000})
  connection.value = 'offline'
  rerender(<OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>)
  await act(async () => release(status(4, false, 999)))
  connection.value = 'ready'
  rerender(<OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>)
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3))
  expect(request.mock.calls[2]?.[1].after).toBe(7)
})

it('accepts a reset snapshot with a lower run ID after a server restart', async () => {
  const reset = status(1, false, 2)
  reset.logs.reset = true
  request.mockResolvedValueOnce(status(9, false, 80)).mockResolvedValueOnce(reset).mockResolvedValue(status(1, false, 3))
  const {container} = render(<OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>)
  await waitFor(() => expect(container.querySelector('.opsi-simulator-panel')?.getAttribute('data-run-id')).toBe('1'), {timeout: 2000})
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3), {timeout: 2000})
  expect(request.mock.calls[2]?.[1].after).toBe(2)
})

it('fetches a full snapshot when a restarted stream has passed the old cursor', async () => {
  let release!: (value: OpsiSimulatorStatus) => void
  const full = new Promise<OpsiSimulatorStatus>(resolve => {release = resolve})
  const partial = status(1, false, 10)
  partial.logs.entries = [{id: 10, level: 'INFO', text: 'partial'}]
  const reset = status(1, false, 10)
  reset.logs.reset = true
  reset.logs.entries = [{id: 1, level: 'INFO', text: 'first entry'}, ...partial.logs.entries]
  request.mockResolvedValueOnce(status(9, false, 7)).mockResolvedValueOnce(partial).mockReturnValueOnce(full).mockResolvedValue(status(1, false, 10))
  const {container} = render(<OpsiSimulatorPanel instance="a" beforeStart={async () => {}}/>)
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3), {timeout: 2000})
  expect(request.mock.calls[1]?.[1].after).toBe(7)
  expect(request.mock.calls[2]?.[1].after).toBe(0)
  expect(container.querySelector('.opsi-simulator-panel')?.getAttribute('data-run-id')).toBe('9')
  expect(screen.queryByText('partial')).toBeNull()
  await act(async () => release(reset))
  expect(container.querySelector('.opsi-simulator-panel')?.getAttribute('data-run-id')).toBe('1')
  expect(screen.getByText('first entry,partial')).toBeTruthy()
  await waitFor(() => expect(request).toHaveBeenCalledTimes(4), {timeout: 2000})
  expect(request.mock.calls[3]?.[1].after).toBe(10)
})

it('ignores an old in-flight poll after starting, including its log cursor', async () => {
  let release!: (value: OpsiSimulatorStatus) => void
  const delayed = new Promise<OpsiSimulatorStatus>(resolve => {release = resolve})
  request.mockImplementation((method: string) => {
    if (method === 'opsi.simulator.start') return Promise.resolve(status(2, true, 17))
    if (method === 'opsi.simulator.status') {
      const count = request.mock.calls.filter(([name]) => name === method).length
      return count === 1 ? Promise.resolve(status(1, false, 3)) : count === 2 ? delayed : Promise.resolve(status(2, true, 17))
    }
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
  expect(statusCalls.at(-1)?.[1].after).toBe(17)
})
