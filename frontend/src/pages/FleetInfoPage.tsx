import {useEffect, useState} from 'react'
import {useParams} from 'react-router-dom'
import {Ship} from 'lucide-react'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/official-ui/switch'
import {Checkbox} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {editor} from '../config/editors'
import {Empty, ErrorBox, Loading, PageTitle} from '../components/ui'
import {LogPanel} from '../components/LogPanel'

export function FleetInfoPage() {
  const {instance = ''} = useParams()
  const {ui, t, instances, notify} = useApp(), connection = useConnection()
  const current = instances.find(item => item.name === instance)
  const scanning = current?.status === 'running' && current.currentTask === 'FleetScan'
  const [value, setValue] = useState<unknown>(), [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [updateEmotion, setUpdateEmotion] = useState(true)
  const reason = connection !== 'ready' ? ui('mind.scanDisconnected')
    : !current ? ui('mind.scanLoading')
    : current.status === 'updating' ? ui('mind.scanUpdating')
    : current.status === 'running' && !scanning ? ui('mind.scanRunning') : ''

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const load = async () => {
      try {
        const config = await api.request('config.get', {instance})
        if (active) {
          setValue(config.values.FleetInfo?.FleetInfo?.Result)
          setUpdateEmotion(config.values.FleetInfo?.FleetInfo?.UpdateEmotion !== false)
          setLoaded(true); setError('')
        }
      } catch (error) {if (active) setError((error as Error).message)}
    }
    void load()
    const timer = scanning ? setInterval(() => void load(), 3000) : undefined
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection, scanning])

  async function toggleScan() {
    setBusy(true); setError('')
    try {
      if (scanning) await api.request('scheduler.stop', {instance})
      else {
        await editor(`config:${instance}`).settled()
        const config = await api.request('config.get', {instance})
        await api.request('config.patch', {instance, revision: config.revision, changes: [
          {path: 'FleetInfo.FleetInfo.UpdateEmotion', value: updateEmotion},
        ]})
        await api.request('tasks.run', {instance, task: 'FleetScan'})
        notify(ui('task.started'))
      }
    } catch (error) {setError((error as Error).message)}
    finally {setBusy(false)}
  }

  return <>
    <PageTitle title={t('Task.FleetInfo.name')} actions={<>
      <span className="flex items-center gap-3"><Checkbox id="fleet-update-emotion" checked={updateEmotion} disabled={!loaded || scanning || busy || !!reason} onCheckedChange={next => setUpdateEmotion(next === true)}/><Label htmlFor="fleet-update-emotion">{ui('fleet.updateEmotion')}</Label></span>
      <span>{t('Task.FleetScan.name')}</span><Switch checked={scanning} aria-label={t('Task.FleetScan.name')} disabled={!loaded || busy || !!reason} title={reason || undefined} onCheckedChange={() => void toggleScan()}/>
    </>}/>
    <p className="muted">{ui('rotation.duplicates')}</p>
    {reason && <p className="muted" role="status">{reason}</p>}
    {error && <ErrorBox message={error}/>}
    {loaded ? <FleetInfo value={value}/> : !error && <Loading/>}
    {scanning && <section className="panel"><h2>{ui('monitor.logs')}</h2><LogPanel/></section>}
  </>
}

export function FleetInfo({value}: {value: unknown}) {
  const {ui} = useApp()
  if (!value || (typeof value === 'object' && !Object.keys(value).length)) return <Empty icon={<Ship size={32}/>} title={ui('fleet.emptyTitle')}>{ui('fleet.emptyHint')}</Empty>
  let fleets: Record<string, Record<string, Array<{name: string; level?: number; emotion?: number | null; slot?: number} | string>>>
  try {fleets = typeof value === 'string' ? JSON.parse(value) : value} catch {return <ErrorBox message={ui('fleet.invalid')}/>}
  const columns = {vanguard: ui('fleet.vanguard'), main: ui('fleet.main'), submarine: ui('fleet.submarine')}
  return <div className="fleet-grid">{[1, 2, 3, 4, 5, 6].map(fleet => <section className="panel" key={fleet}><div className="panel-heading"><h2>{ui('fleet.title', {number: fleet})}</h2><Ship size={18}/></div>{Object.entries(columns).map(([key, label]) => <div className="fleet-column" key={key}><h3>{label}</h3>{fleets[key]?.[fleet]?.length ? fleets[key][fleet].map((ship, index) => <div key={index}>
    <span>{typeof ship !== 'string' && Number.isInteger(ship.slot) && ship.slot! >= 1 && ship.slot! <= 6 ? `${ui('fleet.slot', {number: ship.slot!})} · ` : ''}{typeof ship === 'string' ? ship : ship.name || ui('fleet.unknown')}</span>
    <small>{typeof ship !== 'string' && ship.level ? `Lv.${ship.level} · ` : ''}{ui('fleet.emotion', {value: typeof ship !== 'string' && Number.isInteger(ship.emotion) && ship.emotion! >= 0 && ship.emotion! <= 150 ? ship.emotion! : ui('fleet.unknown')})}</small>
  </div>) : <p>{ui('fleet.noRecord')}</p>}</div>)}</section>)}</div>
}
