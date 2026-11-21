// @vitest-environment jsdom
import {act, renderHook} from '@testing-library/react'
import {afterEach, expect, it, vi} from 'vitest'
import {useAnnouncement, useAnnouncementOwner} from './announcement'

const request = vi.hoisted(() => vi.fn())
vi.mock('../api/client', () => ({api: {request}}))
vi.mock('./context', () => ({useConnection: () => 'ready'}))

afterEach(() => {vi.useRealTimers(); vi.clearAllMocks()})

it('shares one poller, coalesces requests and preserves a forced refresh', async () => {
  vi.useFakeTimers()
  let resolve!: (value: null) => void
  request.mockReturnValueOnce(new Promise<null>(yes => {resolve = yes})).mockResolvedValue(null)
  const owner = renderHook(() => useAnnouncementOwner())
  const first = renderHook(() => useAnnouncement())
  const second = renderHook(() => useAnnouncement())
  expect(request).toHaveBeenCalledTimes(1)
  let refresh!: Promise<void>
  act(() => {refresh = first.result.current.refresh(true); void second.result.current.refresh(false)})
  await act(async () => {resolve(null); await refresh})
  expect(request).toHaveBeenCalledTimes(2)
  expect(request).toHaveBeenLastCalledWith('announcement.get', {force: true})
  expect(first.result.current.ready).toBe(true)
  expect(second.result.current.data).toBeNull()
  await act(async () => {vi.advanceTimersByTime(120_000); await Promise.resolve()})
  expect(request).toHaveBeenCalledTimes(3)
  owner.unmount(); first.unmount(); second.unmount()
  await act(async () => {vi.advanceTimersByTime(120_000); await Promise.resolve()})
  expect(request).toHaveBeenCalledTimes(3)
})
