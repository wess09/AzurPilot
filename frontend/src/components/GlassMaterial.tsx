import { lazy, Suspense } from 'react'
import { useApp } from '../app/context'

const ClassicGlass = lazy(() => import('./ClassicGlass').then(module => ({default: module.ClassicGlass})))
const Wallpaper = lazy(() => import('./Wallpaper').then(module => ({default: module.Wallpaper})))

/** 简约与紧凑不挂载装饰层，也不触发玻璃库和壁纸模块的网络请求。 */
export function GlassMaterial() {
  const {theme} = useApp()
  return theme === 'minimal' || theme === 'extreme' ? null : <Suspense fallback={null}><ClassicGlass/></Suspense>
}

export function ThemeWallpaper() {
  const {theme} = useApp()
  return (theme === 'light' || theme === 'dark') ? <Suspense fallback={null}><Wallpaper/></Suspense> : null
}
