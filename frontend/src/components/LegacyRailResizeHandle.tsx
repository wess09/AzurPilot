/**
 * @fileoverview 调度器栏（总览页左列）宽度拖动调整把手：支持直接拖拽调整、双击重置默认、键盘微调及持久化。
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  getLayout,
  setLegacyRailWidth,
  resetLegacyRailWidth,
  subscribeLayout,
  LEGACY_RAIL_WIDTH_MIN,
  LEGACY_RAIL_WIDTH_MAX,
  LEGACY_RAIL_WIDTH_DEFAULT,
} from '../app/layout'
import {
  readSchedulerPosition,
  subscribeSchedulerPosition,
  type SchedulerPosition,
} from '../app/schedulerPositionPrefs'

const KEYBOARD_STEP = 8

export function LegacyRailResizeHandle({
  side: propSide,
  label = '拖动调整调度器栏宽度（双击恢复默认）',
}: {
  side?: SchedulerPosition
  label?: string
} = {}) {
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const storedSide = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  const side = propSide ?? storedSide
  const [isDragging, setIsDragging] = useState(false)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
  } | null>(null)

  useEffect(() => {
    return () => {
      document.body.classList.remove('is-resizing-rail')
    }
  }, [])

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || dragRef.current) return
    const railWrap = event.currentTarget.closest('.instance-page-rail-wrap') as HTMLElement | null
    const measured = railWrap ? Math.round(railWrap.getBoundingClientRect().width) : 0
    const currentWidth = measured > 0
      ? measured
      : (layout.legacyRailWidth ?? LEGACY_RAIL_WIDTH_DEFAULT)

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
      // 忽略测试环境或不支持指针捕获时的异常
    }
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return

    const deltaX = event.clientX - drag.startX
    const targetWidth = side === 'right' ? drag.startWidth - deltaX : drag.startWidth + deltaX
    setLegacyRailWidth(targetWidth)
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
        // 捕获可能已自动释放
      }
    }
  }

  function handleDoubleClick() {
    resetLegacyRailWidth()
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = layout.legacyRailWidth ?? LEGACY_RAIL_WIDTH_DEFAULT
    switch (event.key) {
      case 'ArrowLeft':
        setLegacyRailWidth(side === 'right' ? current + KEYBOARD_STEP : current - KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'ArrowRight':
        setLegacyRailWidth(side === 'right' ? current - KEYBOARD_STEP : current + KEYBOARD_STEP)
        event.preventDefault()
        break
      case 'Home':
        setLegacyRailWidth(LEGACY_RAIL_WIDTH_MIN)
        event.preventDefault()
        break
      case 'End':
        setLegacyRailWidth(LEGACY_RAIL_WIDTH_MAX)
        event.preventDefault()
        break
      case 'Enter':
      case 'Backspace':
        resetLegacyRailWidth()
        event.preventDefault()
        break
    }
  }

  return (
    <div
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={LEGACY_RAIL_WIDTH_MAX}
      aria-valuemin={LEGACY_RAIL_WIDTH_MIN}
      aria-valuenow={layout.legacyRailWidth ?? LEGACY_RAIL_WIDTH_DEFAULT}
      data-side={side}
      className={`legacy-rail-resize-handle ${isDragging ? 'is-dragging' : ''}`}
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
