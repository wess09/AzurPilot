import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Overview as OverviewData } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { MonitorPanel } from '../components/MonitorPanel'
import { defaultResourceKeys, ResourceCards } from '../components/ResourceCards'
import { InstanceActions } from '../components/InstanceActions'
import { LegacyRail } from '../components/LegacyRail'

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

  const actions = <InstanceActions instance={instance} status={data.status} resources={data.resources} selectedResources={selectedResources} onResourcesChange={updateResourceSelection}/>

  // 旧版版式：左列调度器与任务计划，右列资源卡与日志；右栏在旧版主题下不渲染。
  if (usesLegacyLayout(theme)) return <div className="instance-page-grid">
    <h1 className="legacy-sr-title">{instance}</h1>
    <LegacyRail instance={instance} data={data} onData={setData}>
      <section className="panel legacy-stat-card" aria-label={ui('overview.statCard')}>
        <span className="legacy-stat-title">{ui('overview.statCard')}</span>
        {actions}
      </section>
    </LegacyRail>
    <div className="instance-page-main">
      <ResourceCards resources={data.resources} selected={selectedResources}/>
      <MonitorPanel instance={instance}/>
    </div>
  </div>

  return <div className="overview-page">
    <PageTitle className="instance-page-title" title={instance} actions={actions}/>
    <ResourceCards resources={data.resources} selected={selectedResources}/>
    <div className="overview-main">
      <MonitorPanel instance={instance}/>
    </div>
  </div>
}
