/**
 * @fileoverview 插件页面的导航链接、整页路由与实例内面板的公共渲染入口。
 */
import { NavLink, useParams } from 'react-router-dom'
import { Puzzle } from 'lucide-react'
import { useApp } from '../app/context'
import { ErrorBox, Loading } from '../components/ui'
import { PluginFrame } from './PluginFrame'
import { usePlugins } from './context'
import { pluginAsset, pluginPage } from './types'

/**
 * 渲染启用插件的页面入口链接；按 scope 自动匹配全局或实例内上下文。
 *
 * @param instance - 当前实例名；全局上下文为 undefined。
 * @param onNavigate - 链接点击后的回调，用于收起移动端抽屉。
 */
export function PluginLinks({instance, onNavigate}: {instance?: string; onNavigate?: () => void}) {
  return <>{usePlugins().plugins.filter(plugin => plugin.enabled).flatMap(plugin =>
    plugin.manifest.pages?.filter(page => (page.scope !== 'global') === Boolean(instance)).map(page =>
      <NavLink key={plugin.manifest.id + '/' + page.id} to={pluginPage(plugin, page, instance)} onClick={onNavigate}>
        {page.icon
          ? <img src={pluginAsset(plugin, page.icon)} width={17} height={17} alt="" aria-hidden="true"/>
          : <Puzzle size={17} aria-hidden="true"/>}
        {page.title}
      </NavLink>) ?? [])}</>
}

/** 插件整页路由：按路由参数定位启用插件的页面视图并渲染插件帧。 */
export function PluginPage() {
  const {pluginId, pageId, instance} = useParams()
  const {ui} = useApp()
  const {plugins, ready, error, refresh} = usePlugins()
  if (!ready) return error ? <ErrorBox message={error} retry={refresh}/> : <Loading/>
  const plugin = plugins.find(item => item.enabled && item.manifest.id === pluginId)
  const page = plugin?.manifest.pages?.find(item => item.id === pageId && (item.scope !== 'global') === Boolean(instance))
  if (!plugin || !page) return <ErrorBox message={ui('plugins.pageUnavailable')}/>
  return <section className="panel apu-page">
    <h1 className="panel-heading m-0 text-lg font-semibold">{page.title}</h1>
    <PluginFrame key={plugin.revision + ':' + page.id + ':' + instance}
      plugin={plugin} entry={page.entry} title={page.title} instance={instance}/>
  </section>
}

/** 渲染启用插件声明的全部实例内面板；无面板时不输出节点。 */
export function PluginPanels({instance}: {instance: string}) {
  const panels = usePlugins().plugins.filter(plugin => plugin.enabled).flatMap(plugin =>
    plugin.manifest.panels?.map(panel => <section key={plugin.revision + ':' + panel.id + ':' + instance} className="panel apu-panel">
      <h2 className="panel-heading m-0 text-sm font-semibold">
        {panel.icon && <img src={pluginAsset(plugin, panel.icon)} width={16} height={16} alt="" aria-hidden="true"/>}
        {panel.title}
      </h2>
      <PluginFrame plugin={plugin} entry={panel.entry} title={panel.title} instance={instance}/>
    </section>) ?? [])
  return panels.length > 0 ? <div className="apu-panels">{panels}</div> : null
}
