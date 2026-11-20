import type {SetStateAction} from 'react'
import {useCallback, useEffect, useMemo, useRef, useState} from 'react'

type Waiter = {resolve: () => void; reject: (error: unknown) => void}
type ReadState<T> = {key: string; data?: T; error: string; errorCause?: unknown; busy: boolean; version: number; queued: boolean; queuedSilent: boolean; active: boolean; runId: number; timer?: ReturnType<typeof setTimeout>; waiters: Waiter[]; queuedWaiters: Waiter[]}
const cancelled = () => new DOMException('Read cancelled', 'AbortError')
const rejectWaiters = (waiters: Waiter[]) => {for (const waiter of waiters.splice(0)) waiter.reject(cancelled())}
const newState = <T,>(key: string): ReadState<T> => ({key, error: '', busy: false, version: 0, queued: false, queuedSilent: true, active: false, runId: 0, waiters: [], queuedWaiters: []})

type PollOptions = {when?: () => boolean; silent?: boolean}

/** Read one identity at a time. Concurrent refresh requests coalesce into one trailing read. */
export function usePageRead<T>(identity: string, enabled: boolean, loader: () => Promise<T>, pollAfter?: (data: T | undefined, error: string) => number, {when: canPoll, silent: silentPoll = false}: PollOptions = {}) {
  const [, render] = useState(0)
  const snapshot = useMemo(() => newState<T>(identity), [identity])
  const state = useRef(snapshot)
  const update = useCallback(() => render(value => value + 1), [])
  const request = useCallback((options?: {silent?: boolean}, waiter?: Waiter) => {
    const current = state.current
    if (current !== snapshot || !enabled || !current.active) {waiter?.reject(cancelled()); return}
    if (current.timer) {clearTimeout(current.timer); current.timer = undefined}
    if (current.busy) {
      current.queued = true; current.queuedSilent = current.queuedSilent && !!options?.silent
      if (waiter) current.queuedWaiters.push(waiter)
      return
    }
    if (waiter) current.waiters.push(waiter)
    const schedulePoll = () => {
      const delay = pollAfter?.(current.data, current.error)
      if (delay === undefined || !Number.isFinite(delay) || delay <= 0) return
      current.timer = setTimeout(() => {
        current.timer = undefined
        if (!current.active || state.current !== current) return
        if (canPoll && !canPoll()) schedulePoll()
        else void run(silentPoll)
      }, delay)
    }
    const run = async (silent: boolean) => {
      current.busy = true; current.queued = false; current.queuedSilent = true; update()
      const version = current.version, runId = ++current.runId
      let failure: unknown, failed = false
      try {
        const data = await loader()
        if (state.current === current && current.active && version === current.version) {current.data = data; current.error = ''; current.errorCause = undefined}
      } catch (error) {
        failure = error; failed = true
        if (state.current === current && current.active && version === current.version && (!silent || current.data === undefined)) {
          current.error = error instanceof Error ? error.message : String(error)
          current.errorCause = error
        }
      } finally {
        if (current.runId !== runId || !current.active) return
        if (state.current !== current) {rejectWaiters(current.waiters); rejectWaiters(current.queuedWaiters); return}
        const waiters = current.waiters.splice(0)
        for (const waiter of waiters) failed ? waiter.reject(failure) : waiter.resolve()
        current.busy = false; update()
        if (current.queued) {
          current.waiters = current.queuedWaiters.splice(0)
          void run(current.queuedSilent)
        } else schedulePoll()
      }
    }
    void run(!!options?.silent)
  }, [snapshot, enabled, loader, pollAfter, canPoll, silentPoll, update])
  const reload = useCallback((options?: {silent?: boolean}) => request(options), [request])
  const reloadAndWait = useCallback(() => new Promise<void>((resolve, reject) => request(undefined, {resolve, reject})), [request])
  const invalidate = useCallback(() => {snapshot.version++; snapshot.queued = false; snapshot.queuedSilent = true; rejectWaiters(snapshot.queuedWaiters)}, [snapshot])
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
      snapshot.active = false; snapshot.version++; snapshot.runId++; snapshot.busy = false; snapshot.queued = false; snapshot.queuedSilent = true
      rejectWaiters(snapshot.waiters); rejectWaiters(snapshot.queuedWaiters)
      if (snapshot.timer) {clearTimeout(snapshot.timer); snapshot.timer = undefined}
    }
  }, [snapshot, enabled, reload])
  return {data: snapshot.data, ready: snapshot.data !== undefined, error: snapshot.error, errorCause: snapshot.errorCause, busy: snapshot.busy, reload, reloadAndWait, setData, invalidate}
}
