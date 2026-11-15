// @vitest-environment jsdom
/**
 * @fileoverview 调度器栏拖动把手的交互测试：指针拖拽的方向与增减、键盘步进、快捷键与重置。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ModernRailResizeHandle } from './ModernRailResizeHandle'
import { getLayout, resetModernRailWidth, setModernRailWidth } from '../app/layout'
import { setSchedulerPosition } from '../app/schedulerPositionPrefs'

afterEach(() => {
  cleanup()
  resetModernRailWidth()
  localStorage.clear()
})

beforeEach(() => {
  resetModernRailWidth()
  setSchedulerPosition('left')
})

describe('ModernRailResizeHandle 调度器栏拖动把手', () => {
  it('渲染默认属性、角色与默认左侧 side 标记', () => {
    render(<ModernRailResizeHandle />)
    const handle = screen.getByRole('separator')
    expect(handle).toBeDefined()
    expect(handle.getAttribute('data-side')).toBe('left')
    expect(handle.getAttribute('aria-orientation')).toBe('vertical')
    expect(handle.getAttribute('aria-valuenow')).toBe('280')
  })

  it('显式或偏好为 right 时带有 data-side="right"', () => {
    const { rerender } = render(<ModernRailResizeHandle side="right" />)
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('right')

    setSchedulerPosition('right')
    rerender(<ModernRailResizeHandle />)
    expect(screen.getByRole('separator').getAttribute('data-side')).toBe('right')
  })

  it('左侧布局下向右拖拽增加宽度，向左拖拽减少宽度', () => {
    setModernRailWidth(280)
    render(<ModernRailResizeHandle side="left" />)
    const handle = screen.getByRole('separator')
    // jsdom 未实现 pointer capture：组件在拖拽开始/结束时调用这两个方法，桩掉防止抛错。
    handle.setPointerCapture = vi.fn()
    handle.releasePointerCapture = vi.fn()

    // 模拟从 clientX = 100 开始向右拖拽 50px
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 100 })
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 150 })
    expect(getLayout().railWidth).toBe(330)

    // 向左拖拽 30px（比起始点少 30px）
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 70 })
    expect(getLayout().railWidth).toBe(250)

    fireEvent.pointerUp(handle, { pointerId: 1 })
  })

  it('右侧布局下向左拖拽增加宽度，向右拖拽减少宽度', () => {
    setModernRailWidth(280)
    render(<ModernRailResizeHandle side="right" />)
    const handle = screen.getByRole('separator')
    // jsdom 未实现 pointer capture：桩掉防止抛错，同上。
    handle.setPointerCapture = vi.fn()
    handle.releasePointerCapture = vi.fn()

    // 模拟从 clientX = 800 开始向左拖拽 50px（clientX = 750）
    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientX: 800 })
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 750 })
    expect(getLayout().railWidth).toBe(330)

    // 向右拖拽 30px（clientX = 830）
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 830 })
    expect(getLayout().railWidth).toBe(250)

    fireEvent.pointerUp(handle, { pointerId: 2 })
  })

  it('嵌套在 .instance-page-rail-wrap 且测量宽度为 0 时安全回退至当前宽度/默认值', () => {
    setModernRailWidth(280)
    render(
      <div className="instance-page-rail-wrap">
        <ModernRailResizeHandle side="right" />
      </div>
    )
    const handle = screen.getByRole('separator')
    // jsdom 未实现 pointer capture：桩掉防止抛错，同上。
    handle.setPointerCapture = vi.fn()
    handle.releasePointerCapture = vi.fn()

    // 向左拖拽 40px（从 500 拖到 460）→ 280 + 40 = 320
    fireEvent.pointerDown(handle, { button: 0, pointerId: 10, clientX: 500 })
    fireEvent.pointerMove(handle, { pointerId: 10, clientX: 460 })
    expect(getLayout().railWidth).toBe(320)
    fireEvent.pointerUp(handle, { pointerId: 10 })
  })

  it('双击重置默认宽度', () => {
    setModernRailWidth(360)
    expect(getLayout().railWidth).toBe(360)
    render(<ModernRailResizeHandle />)
    fireEvent.doubleClick(screen.getByRole('separator'))
    expect(getLayout().railWidth).toBeNull()
  })

  it('左侧模式下键盘方向键：ArrowRight 增大，ArrowLeft 缩小', () => {
    setModernRailWidth(280)
    render(<ModernRailResizeHandle side="left" />)
    const handle = screen.getByRole('separator')

    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(getLayout().railWidth).toBe(288)

    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(getLayout().railWidth).toBe(280)
  })

  it('右侧模式下键盘方向键：ArrowLeft 增大，ArrowRight 缩小', () => {
    setModernRailWidth(280)
    render(<ModernRailResizeHandle side="right" />)
    const handle = screen.getByRole('separator')

    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(getLayout().railWidth).toBe(288)

    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    expect(getLayout().railWidth).toBe(280)
  })

  it('键盘快捷键 Home/End/Enter/Backspace 正常响应', () => {
    setModernRailWidth(280)
    render(<ModernRailResizeHandle side="left" />)
    const handle = screen.getByRole('separator')

    fireEvent.keyDown(handle, { key: 'Home' })
    expect(getLayout().railWidth).toBe(220)

    fireEvent.keyDown(handle, { key: 'End' })
    expect(getLayout().railWidth).toBe(560)

    fireEvent.keyDown(handle, { key: 'Enter' })
    expect(getLayout().railWidth).toBeNull()

    setModernRailWidth(300)
    fireEvent.keyDown(handle, { key: 'Backspace' })
    expect(getLayout().railWidth).toBeNull()
  })
})
