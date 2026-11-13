export type ComponentSlot = 'shell' | 'navigation' | 'overview' | 'scheduler' | 'global'
export type OverviewBlock = 'resources' | 'scheduler' | 'queue' | 'logs' | 'panels'
export type PluginPermission = 'instance.read' | 'storage' | 'scheduler.control'

export interface PluginView {
  id: string
  title: string
  entry: string
  scope?: 'global' | 'instance'
  icon?: string
}

export interface PluginTheme {
  navigation?: 'top' | 'left' | 'right' | 'bottom'
  navigationView?: string
  overview?: OverviewBlock[]
  overviewView?: string
  scheduler?: string
  styles?: Partial<Record<ComponentSlot, string>>
  replaceSchedulerStyles?: boolean
  icons?: Partial<Record<'scheduler.start' | 'scheduler.stop' | 'scheduler.title', string>>
}

export interface InstalledPlugin {
  manifest: {
    id: string
    name: string
    version: string
    apiVersion: 1
    theme?: PluginTheme
    permissions?: PluginPermission[]
    pages?: PluginView[]
    panels?: PluginView[]
  }
  enabled: boolean
  revision: string
}

export function pluginAsset(plugin: InstalledPlugin, path: string) {
  return './api/v1/plugins/' + plugin.manifest.id + '/' + plugin.revision + '/' + path.split('/').map(encodeURIComponent).join('/')
}

export function pluginPage(plugin: InstalledPlugin, page: PluginView, instance?: string) {
  const prefix = page.scope !== 'global' && instance ? '/i/' + encodeURIComponent(instance) : ''
  return prefix + '/plugins/' + plugin.manifest.id + '/' + page.id
}
