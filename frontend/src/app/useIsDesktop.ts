/**
 * @fileoverview 响应式桌面端判断。
 */

import { useSyncExternalStore } from 'react'
export function isDesktopDevice(): boolean {
  if (typeof window === 'undefined') return false
  const isWide = window.innerWidth > 950
  const hasFinePointer = typeof window.matchMedia === 'function'
    ? !window.matchMedia('(hover: none)').matches
    : true
  return isWide && hasFinePointer
}

function subscribeDesktop(callback: () => void) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener('resize', callback)
  const hoverMedia = typeof window.matchMedia === 'function' ? window.matchMedia('(hover: none)') : null
  hoverMedia?.addEventListener('change', callback)
  return () => {
    window.removeEventListener('resize', callback)
    hoverMedia?.removeEventListener('change', callback)
  }
}

/**
 * 响应式监听当前是否为桌面端（宽屏且支持鼠标悬停）。
 * SSR / 无 window 环境下默认视作桌面端以保证首屏和已有测试一致。
 */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeDesktop,
    isDesktopDevice,
    () => true
  )
}
