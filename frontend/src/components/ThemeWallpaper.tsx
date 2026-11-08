/**
 * @fileoverview 全局毛玻璃材质背景层挂载组件。
 */

import { lazy, Suspense, useSyncExternalStore } from 'react'
import { getBackground, subscribeBackground } from '../app/background'

const Wallpaper = lazy(() => import('./Wallpaper').then(module => ({default: module.Wallpaper})))

/** 背景开启时按需加载壁纸。 */
export function ThemeWallpaper() {
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  return background.source !== 'off' ? <Suspense fallback={null}><Wallpaper/></Suspense> : null
}
