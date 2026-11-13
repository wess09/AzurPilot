import { NavLink, useParams } from 'react-router-dom'
import { Puzzle } from 'lucide-react'
import { useApp } from '../app/context'
import { ErrorBox, Loading } from '../components/ui'
import { PluginFrame } from './PluginFrame'
import { usePlugins } from './context'
import { pluginAsset, pluginPage } from './types'

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
