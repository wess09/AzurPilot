/**
 * @fileoverview 实例运行总览页面（资源卡、调度器计划与实时日志）。
 */

import { lazy, Suspense, useEffect, useState, useSyncExternalStore } from 'react'
import { useParams } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import type { Overview as OverviewData } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { getLayout, subscribeLayout } from '../app/layout'
import { readSchedulerPosition, subscribeSchedulerPosition } from '../app/schedulerPositionPrefs'
import { ErrorBox, Loading } from '../components/ui'
import { MonitorPanel } from '../components/MonitorPanel'
import { defaultResourceKeys, ResourceCards } from '../components/ResourceCards'
import { InstanceActions } from '../components/InstanceActions'
import { LegacyRail } from '../components/LegacyRail'
import { LegacyRailResizeHandle } from '../components/LegacyRailResizeHandle'
import { readOverviewPanel, setOverviewPanel, subscribeOverviewPanel } from '../app/overviewPanelPrefs'

const Statistics = lazy(() => import('./Statistics').then(module => ({default: module.Statistics})))

function loadResourceSelection(instance: string) {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(`azurpilot.resources.${instance}`) ?? 'null')
    if (Array.isArray(saved) && saved.every(item => typeof item === 'string')) return [...new Set(saved)]
  } catch { /* 损坏偏好使用默认搭配。 */ }
  return defaultResourceKeys
}

export function Overview() {
  const {instance = ''} = useParams()
  const {ui} = useApp()
  const [data, setData] = useState<OverviewData>()
  const [error, setError] = useState('')
  const [selectedResources, setSelectedResources] = useState<string[]>(() => loadResourceSelection(instance))
  const connection = useConnection()
  const panel = useSyncExternalStore(subscribeOverviewPanel, readOverviewPanel, readOverviewPanel)
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  const schedulerPosition = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)

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

  const actions = <InstanceActions resources={data.resources} selectedResources={selectedResources} onResourcesChange={updateResourceSelection}/>

  // 旧版版式：调度器在左列或右列，另一侧是资源卡与日志；右栏在旧版主题下不渲染。
  return <div
    className={`instance-page-grid ${schedulerPosition === 'right' ? 'rail-right' : 'rail-left'}`}
    data-scheduler-position={schedulerPosition}
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
          >{ui(panel === 'stats' ? 'monitor.logs' : 'overview.statCard')}<ChevronRight size={13}/></button>
          {actions}
        </section>
      </LegacyRail>
      <LegacyRailResizeHandle side={schedulerPosition} />
    </div>
    <div className="instance-page-main">
      <ResourceCards resources={data.resources} selected={selectedResources}/>
      {/* 换面板时重挂一次，让内容列的淡入重放；方向类决定从哪一侧滑入。 */}
      <div className={`instance-page-panel ${panel === 'stats' ? 'panel-drop' : 'panel-rise'}`} key={panel}>
        {panel === 'stats'
          ? <div className="instance-panel-stats"><Suspense fallback={<Loading/>}><Statistics/></Suspense></div>
          : <MonitorPanel instance={instance}/>}
      </div>
    </div>
  </div>
}
