/** @fileoverview 任务队列右键菜单：与其他菜单共用 Radix 的定位和键盘操作。 */

import {useEffect, useRef, useState, type ReactElement} from 'react'
import {ContextMenu as Menu} from 'radix-ui'

/** 右键菜单的一个动作项。 */
export interface ContextMenuItem {
  label: string
  run: () => void
  disabled?: boolean
  danger?: boolean
}

/** 触发器沿用调用方元素，菜单经 Portal 定位并在关闭时归还焦点。 */
export function ContextMenu({children, items}: {children: ReactElement; items: ContextMenuItem[]}) {
  const trigger = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    window.addEventListener('blur', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
      window.removeEventListener('blur', close)
    }
  }, [open])

  return <Menu.Root open={open} onOpenChange={setOpen}>
    <Menu.Trigger asChild ref={trigger} onKeyDown={event => {
      if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
      event.preventDefault()
      const bounds = event.currentTarget.getBoundingClientRect()
      event.currentTarget.dispatchEvent(new MouseEvent('contextmenu', {
        bubbles: true, cancelable: true, clientX: bounds.left + 8, clientY: bounds.bottom,
      }))
    }}>{children}</Menu.Trigger>
    <Menu.Portal>
      <Menu.Content className="context-menu" collisionPadding={8} loop onCloseAutoFocus={event => {
        if (trigger.current?.isConnected) {event.preventDefault(); trigger.current.focus()}
      }}>
        {items.map(item => <Menu.Item key={item.label} className={`context-menu-item ${item.danger ? 'danger' : ''}`.trim()}
          disabled={item.disabled} onSelect={item.run}>{item.label}</Menu.Item>)}
      </Menu.Content>
    </Menu.Portal>
  </Menu.Root>
}
