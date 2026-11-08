// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  readSchedulerPosition,
  setSchedulerPosition,
  subscribeSchedulerPosition,
} from './schedulerPositionPrefs'

describe('schedulerPositionPrefs 调度器位置偏好', () => {
  beforeEach(() => {
    localStorage.clear()
    setSchedulerPosition('left')
  })

  it('未设置时默认在左侧', () => {
    expect(readSchedulerPosition()).toBe('left')
  })

  it('存储值为 right 时解析为 right', () => {
    localStorage.setItem('azurpilot.layout.scheduler-position', 'right')
    expect(readSchedulerPosition()).toBe('right')
  })

  it('存储非合法值时回退为 left', () => {
    localStorage.setItem('azurpilot.layout.scheduler-position', 'top')
    expect(readSchedulerPosition()).toBe('left')
  })

  it('写入位置时持久化至 localStorage 并通知订阅者', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeSchedulerPosition(listener)

    setSchedulerPosition('right')
    expect(readSchedulerPosition()).toBe('right')
    expect(localStorage.getItem('azurpilot.layout.scheduler-position')).toBe('right')
    expect(listener).toHaveBeenCalledTimes(1)

    setSchedulerPosition('left')
    expect(readSchedulerPosition()).toBe('left')
    expect(localStorage.getItem('azurpilot.layout.scheduler-position')).toBe('left')
    expect(listener).toHaveBeenCalledTimes(2)

    unsubscribe()
    setSchedulerPosition('right')
    expect(listener).toHaveBeenCalledTimes(2)
  })
})
