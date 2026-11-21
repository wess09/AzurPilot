/**
 * @fileoverview 系统公告拉取、未读状态管理与轮询订阅。
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Announcement } from '../api/types'
import { useConnection } from './context'
import { usePageRead } from './usePageRead'

const READ_KEY = 'azurpilot.announcement.last-read-id'

interface AnnouncementStoreState {
  /** 当前公告；尚无公告时为 null。 */
  data: Announcement | null
  /** 是否正在拉取公告。 */
  loading: boolean
  ready: boolean
  /** 最近一次拉取失败的信息，成功后清空。 */
  error: string
  /** 当前已读的公告 ID。 */
  lastReadId: string | null
}

// 公告状态放在模块级单例：多个组件实例共用一份轮询与未读状态，经 useSyncExternalStore 订阅。
let storeState: AnnouncementStoreState = {
  data: null,
  loading: false,
  ready: false,
  error: '',
  lastReadId: readStoredId(),
}

const listeners = new Set<() => void>()

function notifyListeners() {
  listeners.forEach(fn => fn())
}

function readStoredId(): string | null {
  try {
    return localStorage.getItem(READ_KEY)
  } catch {
    return null
  }
}

function writeStoredId(id: string) {
  try {
    localStorage.setItem(READ_KEY, id)
  } catch {
    /* 存储不可用时会话内生效 */
  }
}

function subscribeAnnouncement(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getAnnouncementSnapshot(): AnnouncementStoreState {
  return storeState
}

let refreshOwner: ((force: boolean) => Promise<void>) | undefined
const pollAnnouncement = () => 120_000

function markAnnouncementAsRead() {
  const currentId = storeState.data?.announcementId
  if (currentId) {
    writeStoredId(currentId)
    storeState = {
      ...storeState,
      lastReadId: currentId,
    }
    notifyListeners()
  }
}

/** Own the shared announcement read once, at the application level. */
export function useAnnouncementOwner() {
  const connection = useConnection()
  const forceNext = useRef(false)
  const load = useCallback(() => {
    const force = forceNext.current
    forceNext.current = false
    return api.request('announcement.get', { force })
  }, [])
  const read = usePageRead('announcement', connection === 'ready', load, pollAnnouncement)
  const {data, ready, busy, error, reloadAndWait} = read

  useEffect(() => {
    storeState = {...storeState, data: data ?? null, ready, loading: busy, error, lastReadId: readStoredId() ?? storeState.lastReadId}
    notifyListeners()
  }, [data, ready, busy, error])

  useEffect(() => {
    if (connection !== 'ready') return
    const refresh = async (force: boolean) => {
      forceNext.current ||= force
      try { await reloadAndWait() } catch { /* Read errors are exposed through the store. */ }
    }
    refreshOwner = refresh
    return () => { if (refreshOwner === refresh) refreshOwner = undefined; forceNext.current = false }
  }, [connection, reloadAndWait])
  return useAnnouncement()
}

/** Subscribe to the shared announcement read and unread state. */
export function useAnnouncement() {
  const state = useSyncExternalStore(subscribeAnnouncement, getAnnouncementSnapshot, getAnnouncementSnapshot)
  const refresh = useCallback(async (force = true) => { await refreshOwner?.(force) }, [])
  const unread = Boolean(state.data?.announcementId && state.data.announcementId !== state.lastReadId)
  return {...state, unread, refresh, markAsRead: markAnnouncementAsRead}
}
