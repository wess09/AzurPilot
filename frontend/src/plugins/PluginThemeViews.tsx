import { useNavigate } from 'react-router-dom'
import { useApp } from '../app/context'
import type { NavigationProps } from '../themes/definition'
import { PluginFrame } from './PluginFrame'
import { usePlugins } from './context'
import { pluginPage } from './types'

export function PluginNavigation({instance, onNavigate, fallback}: NavigationProps) {
  const {ui} = useApp()
  const {theme, plugins} = usePlugins()
  const navigate = useNavigate()
  const entry = theme?.manifest.theme?.navigationView
  if (!theme || !entry) return fallback
  const base = instance ? '/i/' + encodeURIComponent(instance) : ''
  const items = [
    {title: ui('nav.plugins'), to: '/plugins'},
    {title: ui('nav.interface'), to: '/interface'},
    {title: ui('nav.settings'), to: '/settings'},
    {title: ui('nav.configs'), to: '/configs'},
    ...(instance ? [
      {title: ui('nav.overview'), to: base + '/overview'},
      {title: ui('nav.statistics'), to: base + '/statistics'},
      {title: ui('stock.name'), to: base + '/stock-exchange'},
    ] : []),
    ...plugins.filter(plugin => plugin.enabled).flatMap(plugin =>
      plugin.manifest.pages?.filter(page => page.scope === 'global' || instance).map(page =>
        ({title: page.title, to: pluginPage(plugin, page, instance)})) ?? []),
  ]
  return <div className="apu-navigation" data-apu-component="navigation">
    <PluginFrame key={theme.revision + ':' + instance} plugin={theme} entry={entry}
      title={ui('nav.primary')} instance={instance} fallback={fallback}
      navigation={{items, go: to => {onNavigate?.(); navigate(to)}}}/>
  </div>
}
