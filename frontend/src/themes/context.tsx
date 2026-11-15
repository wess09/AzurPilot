/**
 * @fileoverview 主题组件的解析入口：按启用主题的 manifest 决定各槽位使用主题实现还是内置回退。
 */
import { lazy } from 'react'
import { usePlugins } from '../plugins/context'
import type { ThemeComponents } from './definition'

const installedComponents: ThemeComponents = {
  Shell: lazy(() => import('./workbench.theme').then(module => ({default: module.WorkbenchShell}))),
  Navigation: lazy(() => import('../plugins/PluginThemeViews').then(module => ({default: module.PluginNavigation}))),
  Overview: lazy(() => import('./workbench.theme').then(module => ({default: module.WorkbenchOverview}))),
  SchedulerPanel: lazy(() => import('../plugins/PluginScheduler').then(module => ({default: module.PluginScheduler}))),
}

/**
 * 解析指定槽位的组件：启用主题声明了该槽位时返回懒加载的主题实现，否则返回传入的内置组件。
 *
 * @param key - 主题组件槽位名。
 * @param fallback - 主题未启用或未声明该槽位时的内置实现。
 * @returns 最终渲染的组件；主题实现为懒加载组件，调用方需自备 Suspense。
 */
export function useThemeComponent<K extends keyof ThemeComponents>(key: K, fallback: ThemeComponents[K]): ThemeComponents[K] {
  const theme = usePlugins().theme?.manifest.theme
  if (!theme) return fallback
  const enabled = {
    Shell: Boolean(theme.navigation),
    Navigation: Boolean(theme.navigationView),
    Overview: Boolean(theme.overview || theme.overviewView),
    SchedulerPanel: Boolean(theme.scheduler),
  }
  return enabled[key] ? installedComponents[key] : fallback
}
