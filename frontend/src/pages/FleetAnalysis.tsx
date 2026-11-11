import {Button} from '../components/ui/button'
import {Tabs, TabsContent, TabsList, TabsTrigger} from '../components/ui/tabs'
import {useEffect, useRef, useState} from 'react'
import {useParams, useSearchParams} from 'react-router-dom'
import {api} from '../api/client'
import type {DockReport} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, PageTitle} from '../components/ui'
import {useFleetPreference} from '../fleet-tech/preferences'
import {MindCalculator} from './MindCalculator'
import {FleetTechnology} from './FleetTechnology'
import {FleetLedger} from './FleetLedger'
import {ScanUpdate} from './ScanUpdate'
import '../mind/mind.css'
import './fleet-analysis.css'

export function FleetAnalysis() {
  const {instance = ''} = useParams(), [params, setParams] = useSearchParams()
  const {ui} = useApp(), connection = useConnection()
  const [report, setReport] = useState<DockReport>(), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const writing = useRef(false), epoch = useRef(0), refresh = useRef<(() => Promise<void>) | undefined>(undefined)
  const [lastTab, setLastTab] = useFleetPreference<string>(instance, 'tab', 'data')
  const value = params.get('tab') ?? lastTab, tab = value === 'technology' || value === 'mind' || value === 'scan' ? value : 'data'
  useEffect(() => {setLastTab(tab)}, [instance, tab])
  useEffect(() => {writing.current = false; setBusy(false)}, [instance, tab])
  useEffect(() => {
    let active = true, pending = false
    setReport(undefined); setError(''); setBusy(false); writing.current = false; epoch.current++
    if (connection !== 'ready') return
    const load = async () => {
      if (writing.current || pending) return
      pending = true
      const version = epoch.current
      try {const value = await api.request('dock.report', {instance}); if (active && version === epoch.current && !writing.current) {setReport(value); setError('')}}
      catch (e) {if (active && version === epoch.current) setError((e as Error).message)}
      finally {pending = false}
    }
    refresh.current = load
    void load()
    return () => {active = false; refresh.current = undefined}
  }, [instance, connection])
  const onBusy = (value: boolean) => {epoch.current++; writing.current = value; setBusy(value)}
  const onReport = (value: DockReport) => {epoch.current++; setReport(value)}
  return <div className="mind-calculator fleet-analysis"><PageTitle title={ui('analysis.title')} actions={tab !== 'technology' && <Button variant="outline" disabled={busy || connection !== 'ready'} onClick={() => void refresh.current?.()}>{ui('mind.reload')}</Button>}/>{error && <ErrorBox message={error}/>}
    <Tabs value={tab} onValueChange={value => setParams({tab: value}, {replace: true})}>
    <TabsList aria-label={ui('analysis.title')}>{(['technology', 'mind', 'scan', 'data'] as const).map(value => <TabsTrigger key={value} value={value} disabled={busy}>{ui(value === 'scan' ? 'analysis.scanPage' : `analysis.${value}`)}</TabsTrigger>)}</TabsList>
    <TabsContent value={tab}>
      {tab === 'data' && <FleetLedger key={instance} instance={instance} report={report} locked={busy} onReport={onReport} onBusy={onBusy}/>}
      {tab === 'technology' && <FleetTechnology key={instance}/>}
      {tab === 'mind' && <MindCalculator key={instance} report={report} onRefresh={() => refresh.current?.()}/>}
      {tab === 'scan' && <ScanUpdate key={instance} instance={instance} report={report} locked={busy} onReport={onReport} onBusy={onBusy}/>}
    </TabsContent>
    </Tabs>
  </div>
}
