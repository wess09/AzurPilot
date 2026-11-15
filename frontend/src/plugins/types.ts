/**
 * @fileoverview 插件清单与视图的数据类型，以及插件资源、页面 URL 的组装规则。
 */
/** 插件可注入样式或视图的组件槽位。 */
export type ComponentSlot = 'shell' | 'navigation' | 'overview' | 'scheduler' | 'global'
/** 总览页可排序的内容块。 */
export type OverviewBlock = 'resources' | 'scheduler' | 'queue' | 'logs' | 'panels'
/** 插件可申请的受控能力；宿主在消息通道上逐项校验后才放行对应操作。 */
export type PluginPermission = 'instance.read' | 'storage' | 'scheduler.control'

/** 插件提供的可导航视图（页面或面板）描述。 */
export interface PluginView {
  /** URL 中使用的视图标识，同一插件内唯一。 */
  id: string
  /** 展示给用户的标题。 */
  title: string
  /** 插件内相对入口路径。 */
  entry: string
  /** global 表示全局页面，缺省按实例内视图处理。 */
  scope?: 'global' | 'instance'
  /** 导航处展示的图标资源路径。 */
  icon?: string
}

/** 插件 manifest 中的主题皮肤声明。 */
export interface PluginTheme {
  /** 接管主导航时的停靠位置。 */
  navigation?: 'top' | 'left' | 'right' | 'bottom'
  /** 接管主导航的插件视图入口。 */
  navigationView?: string
  /** 内置总览组合布局的块顺序；仅在未声明 overviewView 时生效。 */
  overview?: OverviewBlock[]
  /** 接管整页总览的插件视图入口。 */
  overviewView?: string
  /** 接管总览调度面板的插件视图入口。 */
  scheduler?: string
  /** 按槽位注入的样式表资源路径。 */
  styles?: Partial<Record<ComponentSlot, string>>
  /** 调度器槽位注入样式时是否替换内置样式。 */
  replaceSchedulerStyles?: boolean
  /** 调度器区域图标的资源路径覆盖。 */
  icons?: Partial<Record<'scheduler.start' | 'scheduler.stop' | 'scheduler.title', string>>
}

/** 已安装插件的前端状态，manifest 之外附带启用开关与内容版本。 */
export interface InstalledPlugin {
  /** 后端下发的插件清单。 */
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
  /** 是否启用。 */
  enabled: boolean
  /** 内容修订号，更新后变化，用作资源缓存键。 */
  revision: string
}

/**
 * 组装插件静态资源的相对 URL；路径中按段编码，保留版本缓存语义。
 *
 * @param plugin - 资源所属的插件。
 * @param path - manifest 内声明的资源相对路径。
 * @returns 可直接用于 img/link src 的相对 URL。
 */
export function pluginAsset(plugin: InstalledPlugin, path: string) {
  return './api/v1/plugins/' + plugin.manifest.id + '/' + plugin.revision + '/' + path.split('/').map(encodeURIComponent).join('/')
}

/**
 * 组装插件页面的前端路由地址；实例内视图自动携带实例前缀。
 *
 * @param plugin - 页面所属的插件。
 * @param page - 目标视图描述。
 * @param instance - 当前实例名；全局页面可省略。
 * @returns 可直接用于路由跳转的地址。
 */
export function pluginPage(plugin: InstalledPlugin, page: PluginView, instance?: string) {
  const prefix = page.scope !== 'global' && instance ? '/i/' + encodeURIComponent(instance) : ''
  return prefix + '/plugins/' + plugin.manifest.id + '/' + page.id
}
