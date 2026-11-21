import type {SetStateAction} from 'react'
import {useCallback, useEffect, useMemo, useRef, useState} from 'react'

type Read = {silent: boolean; promise: Promise<void>; resolve: () => void; reject: (error: unknown) => void}
type ReadState<T> = {data?: T; error: string; errorCause?: unknown; version: number; queued?: Read; running?: Read; active: boolean; timer?: ReturnType<typeof setTimeout>}
const cancelled = () => new DOMException('Read cancelled', 'AbortError')
const newRead = (silent: boolean): Read => {
  let resolve!: () => void, reject!: (error: unknown) => void
  const promise = new Promise<void>((yes, no) => {resolve = yes; reject = no})
  // Fire-and-forget reads still need their rejection observed.
  void promise.catch(() => {})
  return {silent, promise, resolve, reject}
}
const newState = <T,>(): ReadState<T> => ({error: '', version: 0, active: false})

type PollOptions = {when?: () => boolean; silent?: boolean}

/** Read one identity at a time. Concurrent refresh requests coalesce into one trailing read. */
export function usePageRead<T>(identity: string, enabled: boolean, loader: (previous: T | undefined) => Promise<T>, pollAfter?: (data: T | undefined, error: string) => number, {when: canPoll, silent: silentPoll = false}: PollOptions = {}) {
  const [, render] = useState(0)
  const snapshot = useMemo(() => newState<T>(), [identity])
  const state = useRef(snapshot)
  const update = useCallback(() => render(value => value + 1), [])
  const request = useCallback((options?: {silent?: boolean}): Promise<void> => {
    const current = state.current
    if (current !== snapshot || !enabled || !current.active) return Promise.reject(cancelled())
    if (current.timer) {clearTimeout(current.timer); current.timer = undefined}
    if (current.running) {
      if (!current.queued) current.queued = newRead(!!options?.silent)
      else current.queued.silent = current.queued.silent && !!options?.silent
      return current.queued.promise
    }
    const schedulePoll = () => {
      const delay = pollAfter?.(current.data, current.error)
      if (delay === undefined || !Number.isFinite(delay) || delay <= 0) return
      current.timer = setTimeout(() => {
        current.timer = undefined
        if (!current.active || state.current !== current) return
        if (canPoll && !canPoll()) schedulePoll()
        else void run(newRead(silentPoll))
      }, delay)
    }
    const run = async (read: Read) => {
      current.running = read; update()
      const version = current.version
      let failure: unknown, failed = false
      try {
        const data = await loader(current.data)
        if (state.current === current && current.active && version === current.version) {current.data = data; current.error = ''; current.errorCause = undefined}
      } catch (error) {
        failure = error; failed = true
        if (state.current === current && current.active && version === current.version && (!read.silent || current.data === undefined)) {
          current.error = error instanceof Error ? error.message : String(error)
          current.errorCause = error
        }
      } finally {
        if (current.running !== read || !current.active) return
        if (state.current !== current) {read.reject(cancelled()); current.queued?.reject(cancelled()); current.queued = undefined; return}
        failed ? read.reject(failure) : read.resolve()
        current.running = undefined; update()
        if (current.queued) {
          const queued = current.queued; current.queued = undefined
          void run(queued)
        } else schedulePoll()
      }
    }
    const read = newRead(!!options?.silent)
    void run(read)
    return read.promise
  }, [snapshot, enabled, loader, pollAfter, canPoll, silentPoll, update])
  const reload = useCallback((options?: {silent?: boolean}) => {void request(options).catch(() => {})}, [request])
  const reloadAndWait = useCallback(() => request(), [request])
  const invalidate = useCallback(() => {snapshot.version++; snapshot.queued?.reject(cancelled()); snapshot.queued = undefined}, [snapshot])
  const setData = useCallback((data: SetStateAction<T | undefined>) => {
    if (state.current !== snapshot) return
    const next = typeof data === 'function' ? (data as (previous: T | undefined) => T | undefined)(snapshot.data) : data
    snapshot.version++
    if (Object.is(next, snapshot.data) && !snapshot.error) return
    snapshot.data = next; snapshot.error = ''; snapshot.errorCause = undefined; update()
  }, [snapshot, update])
  useEffect(() => {
    state.current = snapshot
    snapshot.active = true
    if (enabled) reload()
    return () => {
      snapshot.active = false; snapshot.version++
      snapshot.running?.reject(cancelled()); snapshot.running = undefined
      snapshot.queued?.reject(cancelled()); snapshot.queued = undefined
      if (snapshot.timer) {clearTimeout(snapshot.timer); snapshot.timer = undefined}
    }
  }, [snapshot, enabled, reload])
  return {data: snapshot.data, ready: snapshot.data !== undefined, error: snapshot.error, errorCause: snapshot.errorCause, busy: enabled && !!snapshot.running, reload, reloadAndWait, setData, invalidate}
}
