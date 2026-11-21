/**
 * @fileoverview 调度器栏（总览页左列）宽度拖动调整把手：支持直接拖拽调整、双击重置默认、键盘微调及持久化。
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  getLayout,
  setModernRailWidth,
  resetModernRailWidth,
  subscribeLayout,
  RAIL_WIDTH_MIN,
  RAIL_WIDTH_MAX,
  RAIL_WIDTH_DEFAULT,
} from '../app/layout'
import {
  readSchedulerPosition,
  subscribeSchedulerPosition,
  type SchedulerPosition,
} from '../app/schedulerPositionPrefs'

/** 键盘微调步长（像素/次按键）。 */
const KEYBOARD_STEP = 8

/** 把手的无障碍名称与悬停提示。 */
const HANDLE_LABEL = '拖动调整调度器栏宽度（双击恢复默认）'

/**
 * 总览页页调度器栏的宽度把手（role=separator）：指针拖拽、双击重置默认，
 * 键盘方向键微调、Home/End 直达边界、Enter/Backspace 重置。
 *
 * @param side 把手贴在哪一侧：right 时方向取反（向左拖才加宽）。缺省跟随全局调度器栏位置偏好。
 */
export function ModernRailResizeHandle({
  side: propSide,
}: {
  side?: SchedulerPosition
} = {}) {
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const storedSide = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  const side = propSide ?? storedSide
  const [isDragging, setIsDragging] = useState(false)
  const [renderedWidth, setRenderedWidth] = useState<number | null>(null)
  const handleRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
  } | null>(null)

  // 响应式布局可能限制保存的宽度；无障碍数值始终反映实际栏宽。
  useEffect(() => {
    const railWrap = handleRef.current?.closest('.instance-page-rail-wrap') as HTMLElement | null
    if (!railWrap) return
    const measure = () => {
      const width = Math.round(railWrap.getBoundingClientRect().width)
      setRenderedWidth(width > 0 ? width : null)
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(railWrap)
    window.addEventListener('resize', measure)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])

  function currentRailWidth(handle: HTMLElement) {
    const railWrap = handle.closest('.instance-page-rail-wrap') as HTMLElement | null
    const measured = railWrap ? Math.round(railWrap.getBoundingClientRect().width) : 0
    return measured > 0 ? measured : (layout.railWidth ?? RAIL_WIDTH_DEFAULT)
  }

  // 卸载时兜底移除拖拽态类名：拖拽中途组件被卸载的话，pointerup 与 lostpointercapture 都不会再触发。
  useEffect(() => {
    return () => {
      document.body.classList.remove('is-resizing-rail')
    }
  }, [])

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || dragRef.current) return
    const currentWidth = currentRailWidth(event.currentTarget)

    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: currentWidth,
    }
    setIsDragging(true)
    document.body.classList.add('is-resizing-rail')
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // 忽略测试环境或不支持指针捕获时的异常。
    }
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return

    const deltaX = event.clientX - drag.startX
    const targetWidth = side === 'right' ? drag.startWidth - deltaX : drag.startWidth + deltaX
    setModernRailWidth(targetWidth)
  }

  function handlePointerEnd(event: React.PointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null
      setIsDragging(false)
      document.body.classList.remove('is-resizing-rail')
      try {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId)
        }
      } catch {
        // 捕获可能已自动释放。
      }
    }
  }

  function handleDoubleClick() {
    resetModernRailWidth()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = currentRailWidth(event.currentTarget)
    switch (event.key) {
      case 'ArrowLeft':
        setModernRailWidth(side === 'right' ? current + KEYBOARD_STEP : current - KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'ArrowRight':
        setModernRailWidth(side === 'right' ? current - KEYBOARD_STEP : current + KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'Home':
        setModernRailWidth(RAIL_WIDTH_MIN)
        event.preventDefault()
        break
      case 'End':
        setModernRailWidth(RAIL_WIDTH_MAX)
        event.preventDefault()
        break
      case 'Enter':
      case 'Backspace':
        resetModernRailWidth()
        event.preventDefault()
        break
    }
  }

  return (
    <div
      ref={handleRef}
      aria-label={HANDLE_LABEL}
      aria-orientation="vertical"
      aria-valuemax={Math.max(RAIL_WIDTH_MAX, renderedWidth ?? 0)}
      aria-valuemin={Math.min(RAIL_WIDTH_MIN, renderedWidth ?? RAIL_WIDTH_MIN)}
      aria-valuenow={renderedWidth ?? layout.railWidth ?? RAIL_WIDTH_DEFAULT}
      data-side={side}
      className={`modern-rail-resize-handle ${isDragging ? 'is-dragging' : ''}`}
      onDoubleClick={handleDoubleClick}
      onKeyDown={handleKeyDown}
      onLostPointerCapture={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      role="separator"
      tabIndex={0}
      title={HANDLE_LABEL}
    />
  )
}
