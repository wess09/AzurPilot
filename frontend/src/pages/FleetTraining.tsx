import {useEffect, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {editor} from '../config/editors'
import {ErrorBox, Loading, PageTitle} from '../components/ui'
import {rotationRules} from './FleetRotation'

type Row = {
  level?: number | null; display_level?: number | null; exp?: number | null; affinity?: number | null; checked_at?: string
  completed_for?: Record<string, number>; completed_at?: string; fleet?: number; slot?: number; emotion?: number | null
}
type PositionedRow = Row & {name: string; key: string}
type FleetSnapshot = {name?: string; slot?: number; level?: number; emotion?: number | null; occupied?: boolean; review?: boolean}
type RecordSnapshot = {records: Record<string, Row>; readings?: Record<string, Row & {name?: string}>; formation: unknown; rules: ReturnType<typeof rotationRules>}
const emptySnapshot = (): RecordSnapshot => ({records: {}, formation: {}, rules: rotationRules(undefined)})
const positionNumber = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 6 ? value : undefined
const moraleNumber = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 150 ? value : null

/** 只读归类；先选最近六条历史，再按舰队和舰位排列，不裁剪持久记录。 */
export function trainingRecordGroups({records, readings = {}, formation, rules}: RecordSnapshot) {
  const value = (typeof formation === 'string' ? JSON.parse(formation.trim() || '{}') : formation) as
    Record<string, Record<string, FleetSnapshot[]>> | null
  const ships: (PositionedRow & {review?: boolean})[] = []
  for (const fleet of [1, 2, 3, 4, 5, 6]) for (const category of ['main', 'vanguard']) {
    const entries = value?.[category]?.[fleet]
    if (!Array.isArray(entries)) continue
    for (const ship of entries) {
      const slot = positionNumber(ship?.slot)
      if (!ship || ship.occupied === false || !slot) continue
      ships.push({key: `${fleet}:${slot}`, name: ship.name ?? '', fleet, slot,
        level: ship.level, emotion: moraleNumber(ship.emotion), review: ship.review})
    }
  }
  const byName = new Map<string, PositionedRow>()
  for (const ship of ships)
    if (ship.name && !ship.review && ships.filter(other => other.name === ship.name).length === 1) byName.set(ship.name, ship)
  const isCompleted = (row: Row) => !!row.completed_for && Object.keys(row.completed_for).length > 0
  const atPosition = (a: PositionedRow, b: PositionedRow) => (a.fleet ?? 7) - (b.fleet ?? 7)
    || (a.slot ?? 7) - (b.slot ?? 7) || a.name.localeCompare(b.name)
  const training = ships.filter(ship => rules[String(ship.fleet)]?.slots.includes(ship.slot!))
    .filter(ship => !byName.has(ship.name) || !isCompleted(records[ship.name] ?? {}))
    .map(ship => {
      // 同名的实读只属于当前舰位，不借用按舰名保存的完成记录，也不归入完成分类。
      const position = readings[ship.key]
      const reading = byName.has(ship.name) ? records[ship.name]
        : !ship.review && position?.name === ship.name ? position : undefined
      return {...reading, ...ship, level: reading?.level ?? ship.level}
    }).sort(atPosition)
  const currentNames = new Set(training.filter(ship => byName.has(ship.name)).map(ship => ship.name))
  const rows = Object.entries(records).map(([name, row]) => {
    const current = byName.get(name)
    return {...row, key: name, name,
      fleet: current?.fleet ?? positionNumber(row.fleet), slot: current?.slot ?? positionNumber(row.slot),
      emotion: current ? current.emotion : moraleNumber(row.emotion)}
  })
  const completed = rows.filter(isCompleted)
  const history = rows.filter(row => !isCompleted(row) && !currentNames.has(row.name))
  const recent = (items: PositionedRow[], done: boolean) => [...items]
    .sort((a, b) => ((done ? b.completed_at : undefined) ?? b.checked_at ?? '')
      .localeCompare((done ? a.completed_at : undefined) ?? a.checked_at ?? '') || atPosition(a, b))
    .slice(0, 6).sort(atPosition)
  return {training, completed: recent(completed, true), history: recent(history, false),
    completedCount: completed.length, historyCount: history.length}
}

export function TrainingRecords({snapshot}: {snapshot: RecordSnapshot}) {
  const {ui} = useApp()
  const result = trainingRecordGroups(snapshot)
  return <div style={{display: 'grid', gap: 20}}>
    <p className="muted" style={{margin: 0}}>{ui('training.recordHelp')}</p>
    {(['training', 'completed', 'history'] as const).map(kind => {
      const rows = result[kind], total = kind === 'training' ? rows.length : kind === 'completed' ? result.completedCount : result.historyCount
      return <section className="panel" key={kind} aria-label={ui(`training.${kind}Ships`)} style={{padding: 20, minWidth: 0}}>
        <h2>{ui(`training.${kind}Ships`)} · {rows.length}</h2>
        {kind !== 'training' && <p className="muted">{ui('training.historyLimit', {count: total})}</p>}
        {!rows.length ? <p className="muted">{ui('training.empty')}</p> : <div className="training-record-table" style={{overflowX: 'auto'}}>
          <table className="data-table" style={{width: '100%', minWidth: 900, whiteSpace: 'nowrap', fontSize: 14, padding: 0, borderCollapse: 'collapse'}}>
          <thead><tr><th>{ui('training.fleet')}</th><th>{ui('training.slot')}</th><th>{ui('training.ship')}</th><th>{ui('training.emotion')}</th><th>{ui('training.level')}</th><th>{ui('training.exp')}</th><th>{ui('training.affinity')}</th><th>{ui('training.checkedAt')}</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.key}>
            <td>{row.fleet ? ui('fleet.title', {number: row.fleet}) : ui('training.unread')}</td>
            <td>{row.slot ? ui('fleet.slot', {number: row.slot}) : ui('training.unread')}</td>
            <td>{row.name || ui('fleet.unknown')}</td><td>{row.emotion ?? ui('training.unread')}</td>
            <td title={row.display_level == null ? undefined : ui('training.displayLevel', {level: row.display_level})}>{row.level ?? ui('training.unread')}</td><td>{row.exp ?? ui('training.unread')}</td><td>{row.affinity ?? ui('training.unread')}</td>
            <td>{row.checked_at ? row.checked_at.replace('T', ' ') : ui('training.unread')}</td>
          </tr>)}</tbody>
          </table>
        </div>}
      </section>
    })}
  </div>
}

function recordSnapshot(values: Record<string, Record<string, unknown>>): RecordSnapshot {
  const saved = values.FleetTraining?.State as Pick<RecordSnapshot, 'records' | 'readings'> | undefined
  const snapshot = {records: saved?.records ?? {}, readings: saved?.readings ?? {},
    formation: values.FleetInfo?.Result, rules: rotationRules(values.FleetRotation?.Rules)}
  // 先验证快照；格式错误交给页面现有错误提示，保留上一次可用记录。
  trainingRecordGroups(snapshot)
  return snapshot
}
type Goal = {enabled: boolean; target: string}
const groups = {level: 'FleetLevelTraining', affinity: 'FleetAffinityTraining'} as const
type Metric = keyof typeof groups
const metrics: Metric[] = ['level', 'affinity']

export function FleetTraining() {
  const {instance = ''} = useParams(), {ui, notify, instances} = useApp(), connection = useConnection()
  const [morale, setMorale] = useState(false), [selectedOnly, setSelectedOnly] = useState(false)
  const [dorm, setDorm] = useState(false), [dormFloor, setDormFloor] = useState('floor_1')
  const [hours, setHours] = useState('6')
  const [stopOnComplete, setStopOnComplete] = useState(false), [push, setPush] = useState(false)
  const [settings, setSettings] = useState<Record<Metric, Goal>>({
    level: {enabled: false, target: '120'},
    affinity: {enabled: false, target: '100'},
  })
  const [loaded, setLoaded] = useState(false), [snapshot, setSnapshot] = useState<RecordSnapshot>(emptySnapshot)
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState('')
  const disabled = busy || connection !== 'ready', running = instances.some(item => item.name === instance && item.status === 'running')
  const valid = metrics.every(metric => {
    const {target} = settings[metric], limit = metric === 'level' ? 125 : 200
    return target.trim() !== '' && Number.isInteger(Number(target)) && Number(target) >= 1 && Number(target) <= limit
      && hours.trim() !== '' && Number.isFinite(Number(hours)) && Number(hours) >= 0
  })
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setLoaded(false)
    void api.request('config.get', {instance}).then(config => {
      if (!active) return
      const values = config.values.FleetInfo
      setMorale(values.FleetRotation?.Enabled === true)
      setSelectedOnly(values.FleetRotation?.SelectedOnly === true)
      setDorm(values.FleetDorm?.Enabled === true)
      setDormFloor(values.FleetDorm?.Floor === 'floor_2' ? 'floor_2' : 'floor_1')
      setHours(String(values.FleetTraining?.CheckIntervalHours ?? 6))
      setStopOnComplete(values.FleetTraining?.StopOnComplete === true)
      setPush(values.FleetTraining?.Notify === true)
      setSettings(Object.fromEntries(metrics.map(metric => {
        const value = values[groups[metric]]
        return [metric, {enabled: value?.Enabled === true, target: String(value?.Target ?? (metric === 'level' ? 120 : 100))}]
      })) as Record<Metric, Goal>)
      setSnapshot(recordSnapshot(values))
      setLoaded(true); setDirty(false); setError('')
    }).catch(error => {if (active) setError((error as Error).message)})
    return () => {active = false}
  }, [instance, connection])
  useEffect(() => {
    if (connection !== 'ready' || !running) return
    let active = true
    const timer = setInterval(() => {
      void api.request('config.get', {instance}).then(config => {
        if (active) setSnapshot(recordSnapshot(config.values.FleetInfo))
      }).catch(error => {if (active) setError((error as Error).message)})
    }, 3000)
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection, running])

  function change(metric: Metric, field: 'target', value: string) {
    setSettings(previous => ({...previous, [metric]: {...previous[metric], [field]: value}}))
    setDirty(true)
  }

  async function save(nextMorale = morale, nextSettings = settings, nextDorm = dorm) {
    if (!valid) return
    setBusy(true); setError('')
    try {
      await editor(`config:${instance}`).settled()
      const config = await api.request('config.get', {instance})
      await api.request('config.patch', {instance, revision: config.revision, changes: [
        {path: 'FleetInfo.FleetRotation.Enabled', value: nextMorale},
        {path: 'FleetInfo.FleetRotation.SelectedOnly', value: selectedOnly},
        {path: 'FleetInfo.FleetDorm.Enabled', value: nextDorm},
        {path: 'FleetInfo.FleetDorm.Floor', value: dormFloor},
        {path: 'FleetInfo.FleetTraining.CheckIntervalHours', value: Number(hours)},
        {path: 'FleetInfo.FleetTraining.StopOnComplete', value: stopOnComplete},
        {path: 'FleetInfo.FleetTraining.Notify', value: push},
        ...metrics.flatMap(metric => [
          {path: `FleetInfo.${groups[metric]}.Enabled`, value: nextSettings[metric].enabled},
          {path: `FleetInfo.${groups[metric]}.Target`, value: Number(nextSettings[metric].target)},
        ]),
      ]})
      setMorale(nextMorale); setSettings(nextSettings); setDorm(nextDorm); setDirty(false); notify(ui('training.saved'))
    } catch (error) {setError((error as Error).message)} finally {setBusy(false)}
  }

  async function resetStatus() {
    setBusy(true); setError('')
    try {
      await editor(`config:${instance}`).settled()
      const current = await api.request('config.get', {instance})
      const result = await api.request('fleetTraining.reset', {instance, revision: current.revision})
      setSnapshot(recordSnapshot(result.values.FleetInfo)); notify(ui('training.resetDone'))
    } catch (error) {setError((error as Error).message)} finally {setBusy(false)}
  }

  return <>
    <PageTitle title={ui('training.title')} actions={
      <>
        <button className="button" disabled={disabled || running || !loaded} onClick={() => void resetStatus()}>{ui('training.reset')}</button>
        <button className="button primary" disabled={disabled || !loaded || !dirty || !valid} onClick={() => void save()}>{ui('training.save')}</button>
      </>
    }/>
    <p className="muted">{ui('training.help')}</p>
    <p><Link to={`/i/${instance}/task/FleetSwitch?tab=rotation`}>{ui('training.slotConfig')}</Link></p>
    {error && <ErrorBox message={error}/>}
    {!loaded ? !error && <Loading/> : <>
      <section className="panel" style={{padding: 20, margin: '20px 0'}}>
        <label className="checkbox-label">
          <input type="checkbox" checked={selectedOnly} disabled={disabled} onChange={event => {setSelectedOnly(event.target.checked); setDirty(true)}}/>
          {ui('rotation.selectedOnly')}
        </label>
        <p className="muted">{ui('rotation.emotionHelp')}</p>
        <label style={{display: 'grid', gap: 8, marginTop: 16}}>{ui('training.interval')}
          <input type="number" min={0} step="any" value={hours} disabled={disabled} onChange={event => {setHours(event.target.value); setDirty(true)}}/>
        </label>
        <p className="muted">{ui('training.intervalHelp')}</p>
      </section>
      <div className="fleet-grid" style={{marginBottom: 20}}>
        <section className="panel" aria-label={ui('training.moraleTitle')}>
          <div className="panel-heading"><h2>{ui('training.moraleTitle')}</h2>
            <button type="button" className={`toggle ${morale ? 'on' : ''}`} role="switch" aria-label={ui('training.moraleEnable')} aria-checked={morale} disabled={disabled || !valid} onClick={() => void save(!morale)}><span/></button>
          </div>
          <div style={{padding: 20}}><p className="muted">{ui('training.moraleHelp')}</p></div>
        </section>
        {metrics.map(metric => {
          const goal = settings[metric], isLevel = metric === 'level'
          return <section className="panel" key={metric} aria-label={ui(isLevel ? 'training.levelTitle' : 'training.affinityTitle')}>
            <div className="panel-heading"><h2>{ui(isLevel ? 'training.levelTitle' : 'training.affinityTitle')}</h2>
              <button type="button" className={`toggle ${goal.enabled ? 'on' : ''}`} role="switch" aria-label={ui(isLevel ? 'training.levelEnable' : 'training.affinityEnable')} aria-checked={goal.enabled} disabled={disabled || !valid} onClick={() => void save(morale, {...settings, [metric]: {...goal, enabled: !goal.enabled}})}><span/></button>
            </div>
            <div style={{padding: 20, display: 'grid', gap: 16}}>
              <label style={{display: 'grid', gap: 8}}>{ui(isLevel ? 'training.targetLevel' : 'training.targetAffinity')}
                <input type="number" min={1} max={isLevel ? 125 : 200} step={1} value={goal.target} disabled={disabled} onChange={event => change(metric, 'target', event.target.value)}/>
              </label>
            </div>
          </section>
        })}
        <section className="panel" aria-label={ui('training.dormTitle')}>
          <div className="panel-heading"><h2>{ui('training.dormTitle')}</h2>
            <button type="button" className={`toggle ${dorm ? 'on' : ''}`} role="switch" aria-label={ui('training.dormEnable')} aria-checked={dorm} disabled={disabled || !valid} onClick={() => void save(morale, settings, !dorm)}><span/></button>
          </div>
          <div style={{padding: 20, display: 'grid', gap: 16}}>
            <label style={{display: 'grid', gap: 8}}>{ui('training.dormFloor')}
              <select value={dormFloor} disabled={disabled} onChange={event => {setDormFloor(event.target.value); setDirty(true)}}>
                <option value="floor_1">{ui('training.dormFloor1')}</option>
                <option value="floor_2">{ui('training.dormFloor2')}</option>
              </select>
            </label>
            <p className="muted" style={{margin: 0}}>{ui('training.dormHelp')}</p>
          </div>
        </section>
      </div>
      <section className="panel" style={{padding: 20, margin: '20px 0'}}>
        <label className="checkbox-label">
          <input type="checkbox" checked={stopOnComplete} disabled={disabled} onChange={event => {setStopOnComplete(event.target.checked); setDirty(true)}}/>
          {ui('training.stopOnComplete')}
        </label>
        <p className="muted">{ui('training.stopHelp')}</p>
        <label className="checkbox-label">
          <input type="checkbox" checked={push} disabled={disabled} onChange={event => {setPush(event.target.checked); setDirty(true)}}/>
          {ui('training.notify')}
        </label>
        <p className="muted">{ui('training.notifyHelp')}</p>
      </section>
      <p className="muted">{ui('training.resetHelp')}</p>
      <TrainingRecords snapshot={snapshot}/>
    </>}
  </>
}
