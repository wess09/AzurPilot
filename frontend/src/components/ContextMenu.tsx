/**
 * @fileoverview 区域级右键菜单：受控组件，由调用方决定哪些区域开放哪些动作。
 *
 * 用 `createPortal` 挂到 body：调度器面板带 backdrop-filter 与 FLIP 动画，
 * 菜单留在里面会被当成 containing block，fixed 定位与动画都会被带偏。
 * 打开后点击外部、滚动、失焦、缩放或按 Escape 都关闭。
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface ContextMenuItem {
  label: string
  run: () => void
  disabled?: boolean
  danger?: boolean
}

export function ContextMenu({x, y, items, onClose}: {x: number; y: number; items: ContextMenuItem[]; onClose: () => void}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({x, y})

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && ref.current?.contains(event.target)) return
      onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => {if (event.key === 'Escape') onClose()}
    window.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onClose, true)
    window.addEventListener('blur', onClose)
    window.addEventListener('resize', onClose)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onClose, true)
      window.removeEventListener('blur', onClose)
      window.removeEventListener('resize', onClose)
    }
  }, [onClose])

  // 渲染后量尺寸，贴边时向内翻转。
  useLayoutEffect(() => {
    const menu = ref.current
    if (!menu) return
    setPos({
      x: Math.min(x, window.innerWidth - menu.offsetWidth - 8),
      y: Math.min(y, window.innerHeight - menu.offsetHeight - 8),
    })
  }, [x, y])

  return createPortal(
    <div className="context-menu" role="menu" ref={ref} style={{left: pos.x, top: pos.y}}>
      {items.map((item, index) => (
        <button
          key={index}
          type="button"
          role="menuitem"
          className={`context-menu-item ${item.danger ? 'danger' : ''}`.trim()}
          disabled={item.disabled}
          onClick={() => {item.run(); onClose()}}
        >{item.label}</button>
      ))}
    </div>,
    document.body,
  )
}
