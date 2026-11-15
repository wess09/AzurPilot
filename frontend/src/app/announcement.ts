/**
 * @fileoverview 系统公告拉取、未读状态管理与轮询订阅。
 */

import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Announcement } from '../api/types'
import { useConnection } from './context'

const READ_KEY = 'azurpilot.announcement.last-read-id'

interface AnnouncementStoreState {
  /** 当前公告；尚无公告时为 null。 */
  data: Announcement | null
  /** 是否正在拉取公告。 */
  loading: boolean
  /** 最近一次拉取失败的信息，成功后清空。 */
  error: string
  /** 当前已读的公告 ID。 */
  lastReadId: string | null
}

// 公告状态放在模块级单例：多个组件实例共用一份轮询与未读状态，经 useSyncExternalStore 订阅。
let storeState: AnnouncementStoreState = {
  data: null,
  loading: false,
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

async function fetchAnnouncement(force = false) {
  storeState = { ...storeState, loading: true }
  notifyListeners()
  try {
    const result = await api.request('announcement.get', { force })
    storeState = {
      ...storeState,
      data: result,
      loading: false,
      error: '',
      lastReadId: readStoredId(),
    }
  } catch (err) {
    storeState = {
      ...storeState,
      loading: false,
      error: (err as Error).message || '获取公告失败',
    }
  }
  notifyListeners()
}

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

/**
 * 订阅系统公告并管理未读状态。
 *
 * 连接就绪后拉取一次并转入每 2 分钟的轮询，`refresh` 可强制重新拉取。
 * @returns 公告数据、加载状态、错误、未读状态及读写操作。
 */
export function useAnnouncement() {
  const connection = useConnection()
  const state = useSyncExternalStore(subscribeAnnouncement, getAnnouncementSnapshot, getAnnouncementSnapshot)

  useEffect(() => {
    if (connection !== 'ready') return
    void fetchAnnouncement(false)
    // 之后每 2 分钟后台轮询一次。
    const timer = setInterval(() => {
      void fetchAnnouncement(false)
    }, 120_000)
    return () => clearInterval(timer)
  }, [connection])

  const refresh = useCallback(async (force = true) => {
    if (connection === 'ready') {
      await fetchAnnouncement(force)
    }
  }, [connection])

  const unread = Boolean(
    state.data?.announcementId && state.data.announcementId !== state.lastReadId
  )

  return {
    data: state.data,
    loading: state.loading,
    error: state.error,
    unread,
    refresh,
    markAsRead: markAnnouncementAsRead,
  }
}
