/**
 * @fileoverview 实例运行总览页面（资源卡、调度器计划与实时日志）。
 */

import { useEffect, useState, useSyncExternalStore } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Overview as OverviewData } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { getLayout, subscribeLayout } from '../app/layout'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { MonitorPanel } from '../components/MonitorPanel'
import { defaultResourceKeys, ResourceCards } from '../components/ResourceCards'
import { InstanceActions } from '../components/InstanceActions'
import { LegacyRail } from '../components/LegacyRail'
import { LegacyRailResizeHandle } from '../components/LegacyRailResizeHandle'
import { Statistics } from './Statistics'
import { readOverviewPanel, setOverviewPanel, subscribeOverviewPanel } from '../app/overviewPanelPrefs'

function loadResourceSelection(instance: string) {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(`azurpilot.resources.${instance}`) ?? 'null')
    if (Array.isArray(saved) && saved.every(item => typeof item === 'string')) return [...new Set(saved)]
  } catch { /* 损坏偏好使用默认搭配。 */ }
  return defaultResourceKeys
}

export function Overview() {
  const {instance = ''} = useParams()
  const {theme, ui} = useApp()
  const [data, setData] = useState<OverviewData>()
  const [error, setError] = useState('')
  const [selectedResources, setSelectedResources] = useState<string[]>(() => loadResourceSelection(instance))
  const connection = useConnection()
  const panel = useSyncExternalStore(subscribeOverviewPanel, readOverviewPanel, readOverviewPanel)
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)

  useEffect(() => setSelectedResources(loadResourceSelection(instance)), [instance])

  function updateResourceSelection(keys: string[]) {
    const next = [...new Set(keys)]
    setSelectedResources(next)
    try { localStorage.setItem(`azurpilot.resources.${instance}`, JSON.stringify(next)) } catch { /* 无存储权限时仅本页生效。 */ }
  }

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    void api.request('overview.get', {instance})
      .then(value => { if (active) {setData(value); setError('')} })
      .catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [instance, connection])

  useEffect(() => api.onEvent(event => {
    if (event.topic === 'overview' && (event.data as OverviewData).instance === instance) setData(event.data as OverviewData)
  }), [instance])

  if (error) return <ErrorBox message={error}/>
  if (!data) return <Loading/>

  // 紧凑主题省略与面包屑重复的标题行，设置按钮改挂日志面板工具栏。
  const condensed = theme === 'extreme'
  const actions = <InstanceActions resources={data.resources} selectedResources={selectedResources} onResourcesChange={updateResourceSelection} showLabel={condensed}/>

  // 旧版版式：左列调度器与任务计划，右列资源卡与日志；右栏在旧版主题下不渲染。
  if (usesLegacyLayout(theme)) return <div
    className="instance-page-grid"
    style={layout.legacyRailWidth ? ({'--legacy-rail-width': `${layout.legacyRailWidth}px`} as React.CSSProperties) : undefined}
  >
    <h1 className="legacy-sr-title">{instance}</h1>
    <div className="instance-page-rail-wrap">
      <LegacyRail instance={instance} data={data} onData={setData}>
        {/* 标题即切换主区显示日志还是统计的按钮。 */}
        <section className="panel legacy-stat-card">
          <button type="button" className="legacy-stat-title" aria-pressed={panel === 'stats'}
            aria-label={ui(panel === 'stats' ? 'overview.showLogs' : 'overview.showStats')}
            title={ui(panel === 'stats' ? 'overview.showLogs' : 'overview.showStats')}
            onClick={() => {setOverviewPanel(panel === 'stats' ? 'logs' : 'stats')}}
          >{ui(panel === 'stats' ? 'monitor.logs' : 'overview.statCard')}</button>
          {actions}
        </section>
      </LegacyRail>
      <LegacyRailResizeHandle />
    </div>
    <div className="instance-page-main">
      <ResourceCards resources={data.resources} selected={selectedResources}/>
      {/* 换面板时重挂一次，让内容列的淡入重放；方向类决定从哪一侧滑入。 */}
      <div className={`instance-page-panel ${panel === 'stats' ? 'panel-drop' : 'panel-rise'}`} key={panel}>
        {panel === 'stats'
          ? <div className="instance-panel-stats"><Statistics/></div>
          : <MonitorPanel instance={instance}/>}
      </div>
    </div>
  </div>

  return <div className="overview-page">
    {!condensed && <PageTitle className="instance-page-title" title={instance} actions={actions}/>}
    <ResourceCards resources={data.resources} selected={selectedResources}/>
    <div className="overview-main">
      <MonitorPanel instance={instance} actions={condensed ? actions : undefined}/>
    </div>
  </div>
}
