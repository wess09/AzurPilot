/**
 * @fileoverview 全局毛玻璃材质背景层挂载组件。
 */

import { lazy, Suspense, useLayoutEffect, useSyncExternalStore } from 'react'
import { getBackground, subscribeBackground } from '../app/background'
import { getThemePreference, subscribeTheme } from '../app/theme'

const Wallpaper = lazy(() => import('./Wallpaper').then(module => ({default: module.Wallpaper})))
const getMaterial = () => getThemePreference().material
let softwareRendering: boolean | undefined

/** 只在打开壁纸的玻璃主题上检测一次，避免软件光栅化逐帧重算大面积磨砂。 */
function usesSoftwareRendering() {
  if (softwareRendering !== undefined) return softwareRendering
  try {
    const gl = document.createElement('canvas').getContext('webgl', {failIfMajorPerformanceCaveat: true})
    if (!gl) return softwareRendering = true
    try {
      const info = gl.getExtension('WEBGL_debug_renderer_info')
      const renderer = gl.getParameter(info?.UNMASKED_RENDERER_WEBGL ?? gl.RENDERER)
      softwareRendering = /swiftshader|llvmpipe|softpipe|software|basic render/i.test(String(renderer ?? ''))
    } finally {
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
  } catch {
    softwareRendering = true
  }
  return softwareRendering
}

/** 背景开启时按需加载壁纸。 */
export function ThemeWallpaper() {
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  const material = useSyncExternalStore(subscribeTheme, getMaterial, getMaterial)
  const enabled = background.source !== 'off'
  useLayoutEffect(() => {
    const root = document.documentElement
    root.toggleAttribute('data-reduce-backdrop', material === 'glass' && (!enabled || usesSoftwareRendering()))
    return () => root.removeAttribute('data-reduce-backdrop')
  }, [enabled, material])
  return enabled ? <Suspense fallback={null}><Wallpaper/></Suspense> : null
}
