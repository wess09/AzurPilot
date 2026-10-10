/**
 * @fileoverview 侧栏收起/展开把手（看图模式）：边缘细带 + 指示标记，自带订阅。
 */

import { useEffect, useSyncExternalStore } from 'react'
import { ChevronRight } from 'lucide-react'
import { useApp } from './context'
import { getBackground, subscribeBackground, type BackgroundSnapshot } from './background'
import { getLayout, setSidebarCollapsed, subscribeLayout } from './layout'
import { getThemePreference, showsWallpaper } from './theme'

/** 侧栏收起/展开把手：侧栏边缘一条很细的竖带 + 一枚扁的指示标记，收起时贴屏幕左缘。 */
export function NavHandle({background: given}: {background?: BackgroundSnapshot} = {}) {
  const background = useSyncExternalStore(subscribeBackground, getBackground, () => given ?? getBackground())
  const {ui} = useApp()
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const collapsed = layout.sidebarCollapsed
  /* 看图模式的退出条件是「再次与页面交互」：捕获阶段先折回展开，再让这次交互照常作用到目标上。 */
  useEffect(() => {
    if (!collapsed) return
    const restore = (event: Event) => {
      const target = event.target as HTMLElement | null
      if (target?.closest?.('.nav-handle')) return
      setSidebarCollapsed(false)
    }
    document.addEventListener('pointerdown', restore, true)
    document.addEventListener('keydown', restore, true)
    return () => {
      document.removeEventListener('pointerdown', restore, true)
      document.removeEventListener('keydown', restore, true)
    }
  }, [collapsed])
  /* 只在铺着壁纸时给把手：简约与紧凑族没有壁纸，关闭背景后也没有可看的东西。 */
  if (!showsWallpaper(getThemePreference().theme, background.source)) return null
  return <button
    type="button"
    className="nav-handle"
    aria-label={ui(collapsed ? 'nav.expand' : 'nav.collapse')}
    title={ui(collapsed ? 'nav.expand' : 'nav.collapse')}
    aria-expanded={!collapsed}
    onClick={() => setSidebarCollapsed(!collapsed)}
  ><ChevronRight size={15} aria-hidden="true" style={{transform: collapsed ? 'none' : 'rotate(180deg)'}}/></button>
}
