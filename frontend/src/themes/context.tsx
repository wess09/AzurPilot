import { lazy } from 'react'
import { usePlugins } from '../plugins/context'
import type { ThemeComponents } from './definition'

const installedComponents: ThemeComponents = {
  Shell: lazy(() => import('./workbench.theme').then(module => ({default: module.WorkbenchShell}))),
  Navigation: lazy(() => import('../plugins/PluginThemeViews').then(module => ({default: module.PluginNavigation}))),
  Overview: lazy(() => import('./workbench.theme').then(module => ({default: module.WorkbenchOverview}))),
  SchedulerPanel: lazy(() => import('../plugins/PluginScheduler').then(module => ({default: module.PluginScheduler}))),
}

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
