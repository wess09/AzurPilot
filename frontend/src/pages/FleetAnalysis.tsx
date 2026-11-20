/**
 * @fileoverview 舰船数据页容器：装载船坞报告并分发给台账、舰队科技、养成计算与扫描更新四个标签页。
 */

import {Button} from '../components/ui/button'
import {Tabs, TabsContent, TabsList, TabsTrigger} from '../components/ui/tabs'
import {useCallback, useEffect, useRef, useState} from 'react'
import {useParams, useSearchParams} from 'react-router-dom'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import {usePageRead} from '../app/usePageRead'
import {LoadBoundary} from '../components/ui/load-boundary'
import {useApp, useConnection} from '../app/context'
import {PageTitle} from '../components/ui'
import {useFleetPreference} from '../fleet-tech/preferences'
import {MindCalculator} from './MindCalculator'
import {FleetTechnology} from './FleetTechnology'
import {FleetLedger} from './FleetLedger'
import {ScanUpdate} from './ScanUpdate'
import '../mind/mind.css'
import './fleet-analysis.css'

/**
 * 舰船数据页：装载 dock.report 并分发给数据台账、舰队科技、养成计算与扫描更新四个标签页。
 *
 * 子页经 onBusy/onReport 上报写状态与新报告；写入开始时使正在进行的读取失效，
 * 避免旧装载覆盖子页刚提交的数据。写入期间标签页切换与刷新按钮一并禁用。
 */
export function FleetAnalysis() {
  const {instance = ''} = useParams(), [params, setParams] = useSearchParams()
  const {ui} = useApp(), connection = useConnection()
  const [dockBusy, setDockBusy] = useState(false)
  const loadReport = useCallback(() => api.request('dock.report', {instance}), [instance])
  const read = usePageRead(instance, connection === 'ready', loadReport), report = read.data
  const [technologyBusy, setTechnologyBusy] = useState(false), busy = dockBusy || technologyBusy
  const technologyReload = useRef<(() => void) | undefined>(undefined), mindReload = useRef<(() => void) | undefined>(undefined)
  const [lastTab, setLastTab] = useFleetPreference<string>(instance, 'tab', 'data')
  const value = params.get('tab') ?? lastTab, tab = value === 'technology' || value === 'mind' || value === 'scan' ? value : 'data'
  useEffect(() => {setLastTab(tab)}, [instance, tab])
  useEffect(() => {setDockBusy(false)}, [instance, tab])
  const onBusy = (value: boolean) => {if (value) read.invalidate(); setDockBusy(value)}
  const onReport = (value: DockReport) => read.setData(value)
  return <div className="mind-calculator fleet-analysis"><PageTitle title={ui('analysis.title')} actions={<Button variant="outline" disabled={busy || connection !== 'ready'} onClick={() => {if (tab === 'technology') technologyReload.current?.(); else {read.reload(); if (tab === 'mind') mindReload.current?.()}}}>{ui('mind.reload')}</Button>}/>
    <Tabs value={tab} onValueChange={value => setParams({tab: value}, {replace: true})}>
    <TabsList wrap aria-label={ui('analysis.title')}>{(['technology', 'mind', 'scan', 'data'] as const).map(value => <TabsTrigger key={value} value={value} disabled={dockBusy}>{ui(value === 'scan' ? 'analysis.scanPage' : `analysis.${value}`)}</TabsTrigger>)}</TabsList>
    <TabsContent value={tab}>
      {tab === 'data' && <FleetLedger key={instance} instance={instance} report={report} reportError={read.error} retryReport={read.reload} locked={dockBusy} onReport={onReport} onBusy={onBusy}/>}
      {tab === 'technology' && <FleetTechnology key={instance} reloadRef={technologyReload} busy={technologyBusy} onBusy={setTechnologyBusy}/>}
      {tab === 'mind' && <MindCalculator key={instance} reloadRef={mindReload} report={report} reportError={read.error} onRefresh={read.reload}/>}
      {tab === 'scan' && <LoadBoundary ready={read.ready} error={read.error} retry={read.reload}><ScanUpdate key={instance} instance={instance} report={report} locked={dockBusy} onReport={onReport} onBusy={onBusy}/></LoadBoundary>}
    </TabsContent>
    </Tabs>
  </div>
}
