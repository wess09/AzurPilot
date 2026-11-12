/**
 * @fileoverview 区域级右键菜单：受控组件，由调用方决定哪些区域开放哪些动作。
 *
 * 用 `createPortal` 挂到 body：调度器面板带 backdrop-filter 与 FLIP 动画，
 * 菜单留在里面会被当成 containing block，fixed 定位与动画都会被带偏。
 * 打开后点击外部、滚动、失焦、缩放或按 Escape 都关闭。
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/** 右键菜单的一个动作项；danger 为真时渲染警示样式，用于删除等不可逆操作。 */
export interface ContextMenuItem {
  label: string
  run: () => void
  disabled?: boolean
  danger?: boolean
}

/**
 * 在视口坐标 (x, y) 处弹出动作项列表；打开期间的一切关闭时机都汇入 onClose。
 *
 * @param x 菜单锚点的视口横坐标。
 * @param y 菜单锚点的视口纵坐标。
 */
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

  // 菜单在靠近右/下边缘打开时会溢出视口：渲染后量实际尺寸，把位置夹回视口内（留 8px 余量）。
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
