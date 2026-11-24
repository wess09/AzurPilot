// @vitest-environment jsdom
import {act, renderHook, waitFor} from '@testing-library/react'
import {StrictMode} from 'react'
import {afterEach, describe, expect, it, vi} from 'vitest'
import {usePageRead} from './usePageRead'

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no})
  return {promise, resolve, reject}
}

describe('usePageRead', () => {
  afterEach(() => vi.useRealTimers())
  it('schedules polls after reads, resets timers on reload, and cancels them on unmount', async () => {
    vi.useFakeTimers()
    const loader = vi.fn().mockResolvedValue('ready')
    const poll = () => 1000
    const {result, unmount} = renderHook(() => usePageRead('a', true, loader, poll))
    await act(async () => {})
    await act(async () => {vi.advanceTimersByTime(900); result.current.reload(); await Promise.resolve()})
    expect(loader).toHaveBeenCalledTimes(2)
    await act(async () => {vi.advanceTimersByTime(999); await Promise.resolve()})
    expect(loader).toHaveBeenCalledTimes(2)
    await act(async () => {vi.advanceTimersByTime(1); await Promise.resolve()})
    expect(loader).toHaveBeenCalledTimes(3)
    unmount()
    await act(async () => {vi.advanceTimersByTime(2000); await Promise.resolve()})
    expect(loader).toHaveBeenCalledTimes(3)
  })
  it('skips blocked poll ticks and keeps the last successful value on a silent failure', async () => {
    vi.useFakeTimers()
    let canPoll = false
    const loader = vi.fn().mockResolvedValueOnce('ready').mockRejectedValueOnce(new Error('poll failed'))
    const interval = () => 1000
    const when = () => canPoll
    const {result} = renderHook(() => usePageRead('a', true, loader, interval, {when, silent: true}))
    await act(async () => {})
    await act(async () => {vi.advanceTimersByTime(1000)})
    expect(loader).toHaveBeenCalledTimes(1)
    canPoll = true
    await act(async () => {vi.advanceTimersByTime(1000)})
    expect(loader).toHaveBeenCalledTimes(2)
    expect(result.current.data).toBe('ready')
    expect(result.current.error).toBe('')
  })
  it('does not rerender on an unchanged setData', async () => {
    const loader = vi.fn().mockResolvedValue('ready')
    let renders = 0
    const {result} = renderHook(() => {renders++; return usePageRead<string>('a', true, loader)})
    await waitFor(() => expect(result.current.ready).toBe(true))
    const before = renders
    act(() => result.current.setData(value => value))
    expect(renders).toBe(before)
  })
  it('preserves pushed snapshots against delayed reads and awaits the trailing request', async () => {
    const initial = deferred<string>(), trailing = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(trailing.promise)
    const {result} = renderHook(() => usePageRead('instances', true, loader))
    let finished = false
    let refresh!: Promise<void>
    act(() => {refresh = result.current.reloadAndWait().then(() => {finished = true}); result.current.setData('push')})
    await act(async () => initial.resolve('old'))
    expect(result.current.data).toBe('push')
    expect(finished).toBe(false)
    expect(loader).toHaveBeenCalledTimes(2)
    act(() => result.current.setData((value: string | undefined) => value))
    await act(async () => {trailing.resolve('older'); await refresh})
    expect(result.current.data).toBe('push')
    expect(finished).toBe(true)
  })
  it('passes the accepted value when a trailing read actually starts', async () => {
    const initial = deferred<string>(), trailing = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(trailing.promise)
    const {result} = renderHook(() => usePageRead<string>('a', true, loader))
    expect(loader).toHaveBeenNthCalledWith(1, undefined)
    act(() => {result.current.reload(); result.current.setData('pushed')})
    await act(async () => initial.resolve('obsolete'))
    expect(loader).toHaveBeenNthCalledWith(2, 'pushed')
    await act(async () => trailing.resolve('fresh'))
    expect(result.current.data).toBe('fresh')
  })
  it('propagates refresh failure and cancels pending awaiters on disconnect', async () => {
    const initial = deferred<string>(), refreshResult = deferred<string>(), cancelledResult = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(refreshResult.promise).mockReturnValueOnce(cancelledResult.promise)
    const {result, rerender} = renderHook(({enabled}) => usePageRead('instances', enabled, loader), {initialProps: {enabled: true}})
    await act(async () => initial.resolve('ready'))
    let failed!: Promise<unknown>
    act(() => {failed = result.current.reloadAndWait().catch(error => error)})
    await act(async () => refreshResult.reject(new Error('refresh failed')))
    expect((await failed as Error).message).toBe('refresh failed')
    let pending!: Promise<unknown>
    act(() => {pending = result.current.reloadAndWait().catch(error => error)})
    rerender({enabled: false})
    expect((await pending as Error).name).toBe('AbortError')
    await act(async () => cancelledResult.resolve('late'))
    expect(result.current.data).toBe('ready')
  })
  it('masks the old identity immediately and ignores old success and failure', async () => {
    const a = deferred<string>(), b = deferred<string>()
    const loadA = () => a.promise, loadB = () => b.promise
    const {result, rerender} = renderHook(({key, loader}) => usePageRead(key, true, loader), {initialProps: {key: 'a', loader: loadA}})
    rerender({key: 'b', loader: loadB})
    expect(result.current.data).toBeUndefined()
    await act(async () => {a.reject(new Error('old')); b.resolve('new')})
    expect(result.current.data).toBe('new')
    expect(result.current.error).toBe('')
  })
  it('coalesces reloads, preserves data on failure, and invalidates a read on write', async () => {
    const first = deferred<string>(), second = deferred<string>(), third = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise).mockReturnValueOnce(third.promise)
    const {result} = renderHook(() => usePageRead('a', true, loader))
    act(() => {result.current.reload({silent: true}); result.current.reload()})
    expect(loader).toHaveBeenCalledTimes(1)
    await act(async () => first.resolve('first'))
    expect(loader).toHaveBeenCalledTimes(2)
    await act(async () => second.reject(new Error('failed')))
    expect(result.current.data).toBe('first')
    expect(result.current.error).toBe('failed')
    act(() => result.current.reload())
    act(() => result.current.setData('written'))
    await act(async () => third.resolve('obsolete'))
    await waitFor(() => expect(result.current.busy).toBe(false))
    expect(result.current.data).toBe('written')
    expect(result.current.error).toBe('')
  })
  it('only suppresses silent failures after data exists', async () => {
    const initial = deferred<string>(), retry = deferred<string>(), polling = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(retry.promise).mockReturnValueOnce(polling.promise)
    const {result} = renderHook(() => usePageRead('a', true, loader))
    await act(async () => initial.reject(new Error('initial')))
    expect(result.current.error).toBe('initial')
    act(() => result.current.reload({silent: true}))
    await act(async () => retry.resolve('ready'))
    act(() => result.current.reload({silent: true}))
    await act(async () => polling.reject(new Error('poll')))
    expect(result.current.error).toBe('')
    expect(result.current.data).toBe('ready')
  })
  it('shares one trailing promise and invalidation cancels it without cancelling the active wait', async () => {
    const initial = deferred<string>(), active = deferred<string>(), later = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(active.promise).mockReturnValueOnce(later.promise)
    const {result} = renderHook(() => usePageRead('a', true, loader))
    await act(async () => initial.resolve('initial'))
    let activeWait!: Promise<void>, first!: Promise<void>, second!: Promise<void>
    act(() => {
      activeWait = result.current.reloadAndWait()
      first = result.current.reloadAndWait()
      second = result.current.reloadAndWait()
    })
    expect(first).toBe(second)
    const cancelledWait = first.catch(error => error)
    act(() => result.current.invalidate())
    expect((await cancelledWait as Error).name).toBe('AbortError')
    await act(async () => {active.resolve('obsolete'); await activeWait})
    expect(result.current.data).toBe('initial')
    expect(loader).toHaveBeenCalledTimes(2)
    act(() => {first = result.current.reloadAndWait()})
    await act(async () => {later.resolve('new'); await first})
    expect(result.current.data).toBe('new')
  })
  it('rejects active and trailing waits on disconnect and ignores late completions', async () => {
    const initial = deferred<string>(), active = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(active.promise)
    const {result, rerender} = renderHook(({enabled}) => usePageRead('a', enabled, loader), {initialProps: {enabled: true}})
    await act(async () => initial.resolve('initial'))
    let activeWait!: Promise<unknown>, trailingWait!: Promise<unknown>
    act(() => {
      activeWait = result.current.reloadAndWait().catch(error => error)
      trailingWait = result.current.reloadAndWait().catch(error => error)
    })
    rerender({enabled: false})
    expect((await activeWait as Error).name).toBe('AbortError')
    expect((await trailingWait as Error).name).toBe('AbortError')
    expect(result.current.busy).toBe(false)
    await act(async () => active.resolve('late'))
    expect(result.current.data).toBe('initial')
    expect(result.current.busy).toBe(false)
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('ignores completion from the first StrictMode effect after it restarts', async () => {
    const first = deferred<string>(), second = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const {result} = renderHook(() => usePageRead('a', true, loader), {wrapper: StrictMode})
    expect(loader).toHaveBeenCalledTimes(2)
    await act(async () => first.resolve('stale'))
    expect(result.current.data).toBeUndefined()
    expect(result.current.busy).toBe(true)
    await act(async () => second.resolve('fresh'))
    expect(result.current.data).toBe('fresh')
    expect(result.current.busy).toBe(false)
  })

})
