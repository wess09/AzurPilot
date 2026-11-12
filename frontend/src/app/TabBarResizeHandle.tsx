/**
 * @fileoverview 实例标签栏的尺寸调节把手：拖拽或键盘步进切换标签大小档位，档位状态与持久化在 topbarPrefs。
 */

import { useRef, useSyncExternalStore } from 'react'
import { readTabSize, setTabSize, subscribeTabSize, TAB_SIZES } from './topbarPrefs'

// 每拖 12px 步进一档标签大小。
const DRAG_PIXELS_PER_STEP = 12

/**
 * 标签栏尺寸调节把手：竖直拖拽或方向键、Home、End 在标签大小档位间步进。
 *
 * 拖拽档位始终从按下时的起始档换算，而不是逐档累加，指针中途抖动不会连跳多档；
 * 档位本身存于 topbarPrefs，本组件只负责把拖拽与键盘输入折算成目标档位。
 *
 * @param label 把手的可访问名称，同时用作 aria-label 与悬停提示。
 */
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
      // 只跟踪发起拖拽的那根指针，多指触控时其余指针的移动不改档。
      const start = drag.current
      if (start?.pointerId !== event.pointerId) return
      resize(start.startIndex + Math.round((event.clientY - start.startY) / DRAG_PIXELS_PER_STEP))
    }}
    // 捕获丢失即拖拽结束，复位状态防止后续指针移动继续改档。
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
