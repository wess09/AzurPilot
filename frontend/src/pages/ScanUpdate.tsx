import {useEffect, useRef, useState} from 'react'
import type {ChangeEvent} from 'react'
import {api} from '../api/client'
import type {DockReport, LedgerDifference} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, Loading} from '../components/ui'
import type {MindShip} from '../mind/types'
import type {UiKey} from '../i18n'
import {useFleetPreference} from '../fleet-tech/preferences'

const operationLabels = {
  add: 'analysis.operationAdd', update: 'analysis.operationUpdate',
  remove: 'analysis.operationRemove', resolve: 'analysis.operationResolve',
} as const satisfies Record<LedgerDifference['operation'], UiKey>
const fieldLabels = {
  name: 'analysis.name', level: 'analysis.level', extra_exp: 'analysis.extraExp',
  form: 'analysis.form', owned: 'analysis.owned', full_star: 'analysis.fullStar', lv120: 'analysis.lv120',
} as const satisfies Record<string, UiKey>
function isDisplayField(key: string): key is keyof typeof fieldLabels {
  return Object.hasOwn(fieldLabels, key)
}

export function safeScanChanges(changes: LedgerDifference[]) {return changes.filter(item => item.operation === 'add' || item.operation === 'update')}
export function ScanUpdate({instance, report, locked, onReport, onBusy}: {instance: string; report?: DockReport; locked: boolean; onReport: (report: DockReport) => void; onBusy: (busy: boolean) => void}) {
  const alive = useRef(true)
  useEffect(() => {alive.current = true; return () => {alive.current = false}}, [])
  const publish = (value: DockReport) => {if (alive.current) onReport(value)}
  const {ui, instances, notify} = useApp(), connection = useConnection()
  const [min, setMin] = useFleetPreference<string>(instance, 'scan.min', '1'), [max, setMax] = useFleetPreference<string>(instance, 'scan.max', '125'), [error, setError] = useState(''), [progress, setProgress] = useState('')
  const [targets, setTargets] = useState<Record<string, string>>({}), [removal, setRemoval] = useState('')
  useEffect(() => {setTargets({}); setRemoval('')}, [report?.pending_revision])
  const current = instances.find(item => item.name === instance), scanning = current?.status === 'running' && ['DockScan', 'dock_scan'].includes(current.currentTask ?? '')
  const pending = report?.pending_changes ?? [], safe = safeScanChanges(pending)
  const reading = report?.pending_read
  const disabled = locked || connection !== 'ready' || !report
  const startReason = pending.length ? ui('analysis.pendingBlock') : !current || current.status === 'running' || current.status === 'updating' ? ui('mind.scanRunning') : current.region && current.region !== 'cn' ? ui('mind.scanUnsupported') : ''
  async function action(work: () => Promise<void>) {
    if (disabled) return
    onBusy(true); setError('')
    try {await work()} catch (e) {if (alive.current) setError((e as Error).message)} finally {if (alive.current) onBusy(false)}
  }
  async function run() {
    if (startReason) return
    await action(async () => {
      const low = Number(min), high = Number(max)
      if (!min.trim() || !max.trim() || !Number.isInteger(low) || !Number.isInteger(high) || low < 1 || high > 125 || low > high) throw new Error(ui('mind.invalidRange'))
      publish(await api.request('dock.configure', {instance, min_level: low, max_level: high}))
      if (!alive.current) return
      await api.request('tasks.run', {instance, task: 'DockScan'}); notify(ui('mind.scanStarted'))
    })
  }
  async function exportShips() {
    await action(async () => {
      const latest = await api.request('dock.report', {instance})
      if (!alive.current) return
      publish(latest)
      const exportedAt = new Date().toISOString()
      const blob = new Blob([JSON.stringify({version: 1, exported_at: exportedAt, ...latest}, null, 2) + '\n'], {type: 'application/json;charset=utf-8'})
      const url = URL.createObjectURL(blob), link = document.createElement('a')
      link.href = url
      link.download = `${instance}-ships-${exportedAt.replace(/[:.]/g, '-')}.json`
      document.body.appendChild(link)
      try {link.click()} finally {link.remove(); setTimeout(() => URL.revokeObjectURL(url), 0)}
    })
  }
  async function upload(event: ChangeEvent<HTMLInputElement>, screenshot: boolean) {
    const files = Array.from(event.target.files ?? []); event.target.value = ''
    if (!files.length || pending.length) return
    await action(async () => {
      const ships: MindShip[] = []
      for (const file of files) {
        if (!alive.current) return
        if (file.size > 5_500_000) throw new Error(ui('mind.tooMany'))
        setProgress(file.name)
        const content = await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file)})
        const value = await api.request(screenshot ? 'mind.recognize' : 'mind.import', {instance, filename: file.name, content})
        ships.push(...value.ships)
      }
      if (!alive.current) return
      publish(await api.request('dock.stageImport', {instance, revision: report!.revision, ships})); setProgress(ui('analysis.received'))
    })
  }
  async function review(accept: boolean, items: LedgerDifference[]) {
    await action(async () => {
      publish(await api.request('dock.review', {instance, revision: report!.revision, pending_revision: report!.pending_revision!, decisions: items.map(item => ({id: item.id, accept, ...(accept && item.operation === 'resolve' ? {ship_id: targets[item.id] === 'new' ? null : Number(targets[item.id])} : {})}))}))
    })
  }
  function fieldValue(key: string, value: unknown): string {
    if (key === 'full_star') return ui(value === true ? 'analysis.fullStarYes' : value === false ? 'analysis.fullStarNo' : 'analysis.unknownValue')
    return display(value)
  }
  function display(value: unknown): string {
    if (value === null || value === undefined || value === '') return ui('analysis.unknownValue')
    if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}: ${fieldValue(key, item)}`).join(' / ')
    return String(value)
  }
  function text(value: Record<string, unknown> | null): string {
    if (!value) return '—'
    return Object.entries(value).flatMap(([key, item]) => isDisplayField(key)
      ? [`${ui(fieldLabels[key])}: ${fieldValue(key, item)}`] : []).join(' / ')
  }
  return <div className="fleet-ledger">
    {error && <ErrorBox message={error}/>}{!report && <Loading/>}
    <section className="mind-panel"><h2>1. {ui('analysis.startRead')}</h2><p>{ui('analysis.readFields')}</p><p>{ui('analysis.scanHint')}</p>
      <div className="mind-toolbar"><label>{ui('mind.minLevel')}<input type="number" min={1} max={125} value={min} disabled={disabled || !!startReason} onChange={e => setMin(e.target.value)}/></label><label>{ui('mind.maxLevel')}<input type="number" min={1} max={125} value={max} disabled={disabled || !!startReason} onChange={e => setMax(e.target.value)}/></label><button className="button primary" disabled={disabled || !!startReason} title={startReason} onClick={() => void run()}>{ui('analysis.scan')}</button>{scanning && <button className="button secondary" disabled={disabled} onClick={() => void action(async () => {await api.request('scheduler.stop', {instance})})}>{ui('mind.stop')}</button>}</div>
      <div className="mind-toolbar"><label className="button secondary file-button">{ui('mind.import')}<input type="file" accept=".json,.csv,.xlsx" multiple disabled={disabled || !!pending.length} onChange={event => void upload(event, false)}/></label><label className="button secondary file-button">{ui('mind.screenshots')}<input type="file" accept="image/*" multiple disabled={disabled || !!pending.length} onChange={event => void upload(event, true)}/></label><button className="button secondary" disabled={disabled} title={ui('analysis.exportHint')} onClick={() => void exportShips()}>{ui('analysis.exportJson')}</button></div>
      <p>{ui('analysis.exportHint')}</p>
      {!!pending.length && <p role="status">{ui('analysis.pendingBlock')}</p>}
      <details><summary>{ui('analysis.importLegacy')}</summary><p>{ui('analysis.legacyHint')}</p><button className="button secondary" disabled={disabled || !!pending.length || report?.legacy_imported} onClick={() => void action(async () => {publish(await api.request('dock.importLegacy', {instance, revision: report!.revision})); setProgress(ui('analysis.received'))})}>{ui(report?.legacy_imported ? 'analysis.legacyImported' : 'analysis.importLegacy')}</button></details>
    </section>
    <section className="mind-panel"><h2>2. {ui('analysis.progress')}</h2><p role="status">{scanning ? ui('mind.scanInProgress') : pending.length ? ui('analysis.received') : reading ? ui('analysis.readSaved') : progress || ui('analysis.empty')}</p><p>{ui('analysis.readCount')}: {reading?.observed_count ?? '—'} · {ui('analysis.review')}: {reading?.review_count ?? '—'} · {ui(reading?.complete ? 'analysis.complete' : 'analysis.partial')}</p>{reading && <p>{ui('analysis.time')}: {reading.updated_at} · {reading.source}</p>}<p>{ui('analysis.confirmedCount')}: {report?.ships.length ?? 0} · {ui('analysis.pendingCount')}: {pending.length}</p></section>
    <section className="mind-panel"><h2>3. {ui('analysis.pending')}</h2><p>{ui('analysis.pendingHint')}</p>
      <p>{Object.entries(operationLabels).map(([operation, label]) => `${ui(label)}: ${pending.filter(item => item.operation === operation).length}`).join(' · ')}</p>
      <div className="mind-toolbar"><button className="button primary" disabled={disabled || !safe.length} onClick={() => void review(true, safe)}>{ui('analysis.safeAccept')} ({safe.length})</button><button className="button secondary" disabled={disabled || !pending.length} onClick={() => void review(false, pending)}>{ui('analysis.rejectAll')}</button></div>
      {!pending.length && <p>{ui('analysis.noPending')}</p>}
      {pending.map(item => <article className="ledger-difference" key={item.id}><h3>{item.name || ui(item.kind === 'technology' ? 'analysis.technologyKind' : item.kind === 'nation' ? 'analysis.nationKind' : 'analysis.shipKind')} · {ui(operationLabels[item.operation])}</h3><p>{ui('analysis.before')}: {text(item.before)}</p><p>{ui('analysis.after')}: {text(item.after)}</p>
        {item.operation === 'resolve' && <label>{ui('analysis.target')}<select aria-label={`${ui('analysis.target')} ${item.id}`} disabled={disabled} value={targets[item.id] ?? ''} onChange={e => setTargets({...targets, [item.id]: e.target.value})}><option value="">{ui('analysis.chooseTarget')}</option><option value="new">{ui('analysis.addAsNew')}</option>{item.candidates.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.name} #{candidate.id} · Lv.{candidate.level}</option>)}</select></label>}
        {item.operation === 'remove' && <p>{ui('analysis.retireHint')}</p>}
        <button className="button primary" disabled={disabled || item.operation === 'resolve' && !targets[item.id]} aria-label={`${ui('analysis.accept')} ${item.id}`} onClick={() => {if (item.operation === 'remove' && removal !== item.id) setRemoval(item.id); else void review(true, [item])}}>{ui(item.operation === 'remove' && removal === item.id ? 'analysis.retireConfirm' : 'analysis.accept')}</button>{' '}<button className="button secondary" disabled={disabled} onClick={() => void review(false, [item])}>{ui('analysis.reject')}</button>
      </article>)}
    </section>
  </div>
}
