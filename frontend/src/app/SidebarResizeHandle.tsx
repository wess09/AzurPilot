/**
 * @fileoverview 侧边栏宽度拖动调整把手：支持直接拖拽调整、双击重置默认、键盘微调及持久化。
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  clampSidebarWidth,
  getLayout,
  setSidebarWidth,
  resetSidebarWidth,
  subscribeLayout,
  SIDEBAR_WIDTH_MIN,
  SIDEBAR_WIDTH_MAX,
} from './layout'

const KEYBOARD_STEP = 8

/**
 * 提供侧栏宽度的无障碍调整入口：拖动改宽，双击或 Enter/Backspace 恢复默认，
 * 左右方向键按步长微调，Home/End 到达上下限；宽度变化写入 layout store 持久化。
 *
 * @param label 把手的 aria-label 与 title 提示文案。
 */
export function SidebarResizeHandle({label = '拖动调整侧边栏宽度（双击恢复默认）'}: {label?: string}) {
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const [isDragging, setIsDragging] = useState(false)
  const [previewWidth, setPreviewWidth] = useState<number>()
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
    sidebar: HTMLElement | null
    width?: number
    frame?: number
  } | null>(null)

  function clearDrag() {
    const drag = dragRef.current
    if (!drag) return
    dragRef.current = null
    if (drag.frame !== undefined) cancelAnimationFrame(drag.frame)
    drag.sidebar?.style.removeProperty('--sidebar-width-preview')
    document.body.classList.remove('is-resizing-sidebar')
  }

  useEffect(() => clearDrag, [])

  // 看图模式收起侧栏时不显示把手。
  if (layout.sidebarCollapsed) return null

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || dragRef.current) return
    const sidebar = event.currentTarget.closest('.sidebar') as HTMLElement | null
    const currentWidth = sidebar
      ? Math.round(sidebar.getBoundingClientRect().width)
      : (layout.sidebarWidth ?? 200)

    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: currentWidth,
      sidebar,
    }
    setIsDragging(true)
    document.body.classList.add('is-resizing-sidebar')
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return

    const width = clampSidebarWidth(drag.startWidth + event.clientX - drag.startX)
    if (drag.width === width) return
    drag.width = width
    if (drag.frame !== undefined) return
    drag.frame = requestAnimationFrame(() => {
      drag.frame = undefined
      drag.sidebar?.style.setProperty('--sidebar-width-preview', `${drag.width}px`)
      setPreviewWidth(drag.width)
    })
  }

  // 指针捕获因切窗口等意外丢失时也按松手收尾，否则拖拽状态会卡在 is-dragging。
  function handlePointerEnd(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (drag?.pointerId !== event.pointerId) return
    if (drag.width !== undefined) setSidebarWidth(drag.width)
    clearDrag()
    setPreviewWidth(undefined)
    setIsDragging(false)
  }

  function handleDoubleClick() {
    resetSidebarWidth()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = layout.sidebarWidth ?? 200
    switch (event.key) {
      case 'ArrowLeft':
        setSidebarWidth(current - KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'ArrowRight':
        setSidebarWidth(current + KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'Home':
        setSidebarWidth(SIDEBAR_WIDTH_MIN)
        event.preventDefault()
        break
      case 'End':
        setSidebarWidth(SIDEBAR_WIDTH_MAX)
        event.preventDefault()
        break
      case 'Enter':
      case 'Backspace':
        resetSidebarWidth()
        event.preventDefault()
        break
    }
  }

  return (
    <div
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={SIDEBAR_WIDTH_MAX}
      aria-valuemin={SIDEBAR_WIDTH_MIN}
      aria-valuenow={previewWidth ?? layout.sidebarWidth ?? undefined}
      className={`sidebar-resize-handle ${isDragging ? 'is-dragging' : ''}`}
      onDoubleClick={handleDoubleClick}
      onKeyDown={handleKeyDown}
      onLostPointerCapture={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      role="separator"
      tabIndex={0}
      title={label}
    />
  )
}
