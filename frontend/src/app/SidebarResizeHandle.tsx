/**
 * @fileoverview 侧边栏宽度拖动调整把手：支持直接拖拽调整、双击重置默认、键盘微调及持久化。
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
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
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
  } | null>(null)

  // 卸载时兜底摘掉拖拽态类：拖拽中途组件被卸载的话，body 上的 col-resize 光标与禁用选中会残留。
  useEffect(() => {
    return () => {
      document.body.classList.remove('is-resizing-sidebar')
    }
  }, [])

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
    }
    setIsDragging(true)
    document.body.classList.add('is-resizing-sidebar')
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return

    const deltaX = event.clientX - drag.startX
    const targetWidth = drag.startWidth + deltaX
    setSidebarWidth(targetWidth)
  }

  // 指针捕获因切窗口等意外丢失时也按松手收尾，否则拖拽状态会卡在 is-dragging。
  function handlePointerEnd(event: React.PointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null
      setIsDragging(false)
      document.body.classList.remove('is-resizing-sidebar')
    }
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
      aria-valuenow={layout.sidebarWidth ?? undefined}
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
