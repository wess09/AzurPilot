/**
 * @fileoverview 预览层焦点圈定：Tab 循环不出覆盖层、焦点逃逸即拉回；卸载时把焦点还给打开预览前的元素。
 * 从 MockInstancePreview.tsx 原 76-105 行提取，纯搬迁未改动（焦点圈定副作用改为独立 Hook）。
 */
import { useEffect, type RefObject } from 'react'

/** 把键盘焦点圈定在覆盖层内，关闭时恢复触发前的焦点位置。 */
export function useFocusTrap(overlayRef: RefObject<HTMLDivElement | null>) {
  // Tab 循环不出覆盖层、焦点逃逸即拉回；卸载时把焦点还给打开预览前的元素。
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const root = overlayRef.current
    if (!root) return
    const focusable = () => [...root.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')]
      .filter(element => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0)
    const focusFirst = () => (focusable()[0] ?? root).focus()
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = focusable()
      const current = items.indexOf(document.activeElement as HTMLElement)
      if (!items.length || current < 0 || (event.shiftKey ? current === 0 : current === items.length - 1)) {
        event.preventDefault()
        ;(event.shiftKey ? items.at(-1) ?? root : items[0] ?? root).focus()
      }
    }
    const containFocus = (event: FocusEvent) => {
      if (!root.contains(event.target as Node)) focusFirst()
    }
    focusFirst()
    document.addEventListener('keydown', trapFocus, true)
    document.addEventListener('focusin', containFocus)
    return () => {
      document.removeEventListener('keydown', trapFocus, true)
      document.removeEventListener('focusin', containFocus)
      if (previous?.isConnected) previous.focus()
    }
  }, [])
}
