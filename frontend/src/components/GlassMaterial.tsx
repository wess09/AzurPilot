import { lazy, Suspense } from 'react'
import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'

const ClassicGlass = lazy(() => import('./ClassicGlass').then(module => ({default: module.ClassicGlass})))
const Wallpaper = lazy(() => import('./Wallpaper').then(module => ({default: module.Wallpaper})))

/** 朴素主题不挂载装饰层，也不触发玻璃库和壁纸模块的网络请求。 */
export function GlassMaterial() {
  const {theme} = useApp()
  return usesMaterial(theme) ? <Suspense fallback={null}><ClassicGlass/></Suspense> : null
}

export function ThemeWallpaper() {
  const {theme} = useApp()
  return usesMaterial(theme) ? <Suspense fallback={null}><Wallpaper/></Suspense> : null
}
