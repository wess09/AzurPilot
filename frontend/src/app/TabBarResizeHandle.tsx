import { useRef, useSyncExternalStore } from 'react'
import { readTabSize, setTabSize, subscribeTabSize, TAB_SIZES } from './topbarPrefs'

const DRAG_PIXELS_PER_STEP = 12

export function TabBarResizeHandle({label}: {label: string}) {
  const size = useSyncExternalStore(subscribeTabSize, readTabSize, readTabSize)
  const index = TAB_SIZES.indexOf(size)
  const drag = useRef<{pointerId: number; startY: number; startIndex: number} | null>(null)

  function resize(nextIndex: number) {
    const next = TAB_SIZES[Math.max(0, Math.min(nextIndex, TAB_SIZES.length - 1))]
    if (next !== readTabSize()) setTabSize(next)
  }

  return <div
    className="tabbar-resize-handle"
    role="slider"
    tabIndex={0}
    aria-label={label}
    aria-orientation="vertical"
    aria-valuemin={1}
    aria-valuemax={TAB_SIZES.length}
    aria-valuenow={index + 1}
    title={label}
    onPointerDown={event => {
      if (event.button !== 0 || drag.current) return
      drag.current = {pointerId: event.pointerId, startY: event.clientY, startIndex: index}
      event.currentTarget.setPointerCapture(event.pointerId)
    }}
    onPointerMove={event => {
      const start = drag.current
      if (start?.pointerId !== event.pointerId) return
      resize(start.startIndex + Math.round((event.clientY - start.startY) / DRAG_PIXELS_PER_STEP))
    }}
    onLostPointerCapture={() => {drag.current = null}}
    onKeyDown={event => {
      switch (event.key) {
        case 'ArrowDown':
        case 'ArrowRight':
          resize(index + 1)
          break
        case 'ArrowUp':
        case 'ArrowLeft':
          resize(index - 1)
          break
        case 'Home':
          resize(0)
          break
        case 'End':
          resize(TAB_SIZES.length - 1)
          break
        default:
          return
      }
      event.preventDefault()
    }}
  />
}
