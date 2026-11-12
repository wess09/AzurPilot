/**
 * @fileoverview 船坞扫描与待确认差异确认页：配置扫描或导入舰船快照，查看读取进度，逐条确认入库。
 */

import {Button} from '../components/ui/button'
import {useEffect, useRef, useState} from 'react'
import type {ChangeEvent} from 'react'
import {api} from '../api/client'
import type {DockReport, LedgerDifference} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, Loading} from '../components/ui'
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '../components/official-ui/select'
import {Input} from '../components/official-ui/input'
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

/**
 * 筛出可整批接受的安全变更（只含 add/update），对应「确认无歧义的新增和更新」按钮；
 * resolve 要逐条指定目标卡片、remove 要二次确认，都不进这一批。
 */
export function safeScanChanges(changes: LedgerDifference[]) {return changes.filter(item => item.operation === 'add' || item.operation === 'update')}
/**
 * 船坞扫描更新页：三段式流程——开始读取（扫描/导入）、读取进度、逐条确认待确认差异。
 * 写操作都携带当前 report.revision 提交；组件卸载后的异步回调一律丢弃。
 *
 * @param report 最近一次确认的船坞报告，缺省时页面停在加载态。
 * @param locked 外层锁定开关，锁定时全部操作禁用。
 */
export function ScanUpdate({instance, report, locked, onReport, onBusy}: {instance: string; report?: DockReport; locked: boolean; onReport: (report: DockReport) => void; onBusy: (busy: boolean) => void}) {
  // alive 挡住卸载后的迟到回调：扫描、导入的耗时可能超过用户停留在页面的时间。
  const alive = useRef(true)
  const importInput = useRef<HTMLInputElement>(null), screenshotInput = useRef<HTMLInputElement>(null)
  useEffect(() => {alive.current = true; return () => {alive.current = false}}, [])
  const publish = (value: DockReport) => {if (alive.current) onReport(value)}
  const {ui, instances, notify} = useApp(), connection = useConnection()
  const [min, setMin] = useFleetPreference<string>(instance, 'scan.min', '1'), [max, setMax] = useFleetPreference<string>(instance, 'scan.max', '125'), [error, setError] = useState(''), [progress, setProgress] = useState('')
  const [targets, setTargets] = useState<Record<string, string>>({}), [removal, setRemoval] = useState('')
  // 新一轮待确认差异到达后，旧的目标卡片选择与移除确认全部作废。
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
      // 导出前重新拉一次报告：不沿用页面上的旧快照，文件里始终是最新确认结果。
      const latest = await api.request('dock.report', {instance})
      if (!alive.current) return
      publish(latest)
      const exportedAt = new Date().toISOString()
      const blob = new Blob([JSON.stringify({version: 1, exported_at: exportedAt, ...latest}, null, 2) + '\n'], {type: 'application/json;charset=utf-8'})
      const url = URL.createObjectURL(blob), link = document.createElement('a')
      link.href = url
      link.download = `${instance}-ships-${exportedAt.replace(/[:.]/g, '-')}.json`
      document.body.appendChild(link)
      // 回收 blob URL 延后到下一个事件循环：下载请求还没发完就被回收可能截断下载。
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
        // reader.result 是 dataURL：按第一个逗号切掉前缀，只把 base64 内容发给接口。
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
      // 目标卡片选「新增独立卡片」时 ship_id 传 null：null 即不归属任何已有舰船。
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
      <div className="mind-toolbar"><label>{ui('mind.minLevel')}<Input type="number" min={1} max={125} value={min} disabled={disabled || !!startReason} onChange={e => setMin(e.target.value)}/></label><label>{ui('mind.maxLevel')}<Input type="number" min={1} max={125} value={max} disabled={disabled || !!startReason} onChange={e => setMax(e.target.value)}/></label><Button disabled={disabled || !!startReason} title={startReason} onClick={() => void run()}>{ui('analysis.scan')}</Button>{scanning && <Button variant="outline" disabled={disabled} onClick={() => void action(async () => {await api.request('scheduler.stop', {instance})})}>{ui('mind.stop')}</Button>}</div>
      <div className="mind-toolbar"><Button type="button" variant="outline" disabled={disabled || !!pending.length} onClick={() => importInput.current?.click()}>{ui('mind.import')}</Button><input ref={importInput} type="file" accept=".json,.csv,.xlsx" multiple hidden disabled={disabled || !!pending.length} onChange={event => void upload(event, false)}/><Button type="button" variant="outline" disabled={disabled || !!pending.length} onClick={() => screenshotInput.current?.click()}>{ui('mind.screenshots')}</Button><input ref={screenshotInput} type="file" accept="image/*" multiple hidden disabled={disabled || !!pending.length} onChange={event => void upload(event, true)}/><Button variant="outline" disabled={disabled} title={ui('analysis.exportHint')} onClick={() => void exportShips()}>{ui('analysis.exportJson')}</Button></div>
      <p>{ui('analysis.exportHint')}</p>
      {!!pending.length && <p role="status">{ui('analysis.pendingBlock')}</p>}
      <details><summary>{ui('analysis.importLegacy')}</summary><p>{ui('analysis.legacyHint')}</p><Button variant="outline" disabled={disabled || !!pending.length || report?.legacy_imported} onClick={() => void action(async () => {publish(await api.request('dock.importLegacy', {instance, revision: report!.revision})); setProgress(ui('analysis.received'))})}>{ui(report?.legacy_imported ? 'analysis.legacyImported' : 'analysis.importLegacy')}</Button></details>
    </section>
    <section className="mind-panel"><h2>2. {ui('analysis.progress')}</h2><p role="status">{scanning ? ui('mind.scanInProgress') : pending.length ? ui('analysis.received') : reading ? ui('analysis.readSaved') : progress || ui('analysis.empty')}</p><p>{ui('analysis.readCount')}: {reading?.observed_count ?? '—'} · {ui('analysis.review')}: {reading?.review_count ?? '—'} · {ui(reading?.complete ? 'analysis.complete' : 'analysis.partial')}</p>{reading && <p>{ui('analysis.time')}: {reading.updated_at} · {reading.source}</p>}<p>{ui('analysis.confirmedCount')}: {report?.ships.length ?? 0} · {ui('analysis.pendingCount')}: {pending.length}</p></section>
    <section className="mind-panel"><h2>3. {ui('analysis.pending')}</h2><p>{ui('analysis.pendingHint')}</p>
      <p>{Object.entries(operationLabels).map(([operation, label]) => `${ui(label)}: ${pending.filter(item => item.operation === operation).length}`).join(' · ')}</p>
      <div className="mind-toolbar"><Button disabled={disabled || !safe.length} onClick={() => void review(true, safe)}>{ui('analysis.safeAccept')} ({safe.length})</Button><Button variant="outline" disabled={disabled || !pending.length} onClick={() => void review(false, pending)}>{ui('analysis.rejectAll')}</Button></div>
      {!pending.length && <p>{ui('analysis.noPending')}</p>}
      {pending.map(item => <article className="ledger-difference" key={item.id}><h3>{item.name || ui(item.kind === 'technology' ? 'analysis.technologyKind' : item.kind === 'nation' ? 'analysis.nationKind' : 'analysis.shipKind')} · {ui(operationLabels[item.operation])}</h3><p>{ui('analysis.before')}: {text(item.before)}</p><p>{ui('analysis.after')}: {text(item.after)}</p>
        {item.operation === 'resolve' && <label>{ui('analysis.target')}<Select disabled={disabled} value={targets[item.id] || '__choose__'} onValueChange={value => setTargets({...targets, [item.id]: value === '__choose__' ? '' : value})}><SelectTrigger aria-label={`${ui('analysis.target')} ${item.id}`}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__choose__">{ui('analysis.chooseTarget')}</SelectItem><SelectItem value="new">{ui('analysis.addAsNew')}</SelectItem>{item.candidates.map(candidate => <SelectItem key={candidate.id} value={String(candidate.id)}>{candidate.name} #{candidate.id} · Lv.{candidate.level}</SelectItem>)}</SelectContent></Select></label>}
        {item.operation === 'remove' && <p>{ui('analysis.retireHint')}</p>}
        <Button disabled={disabled || item.operation === 'resolve' && !targets[item.id]} aria-label={`${ui('analysis.accept')} ${item.id}`} onClick={() => {if (item.operation === 'remove' && removal !== item.id) setRemoval(item.id); else void review(true, [item])}}>{ui(item.operation === 'remove' && removal === item.id ? 'analysis.retireConfirm' : 'analysis.accept')}</Button>{' '}<Button variant="outline" disabled={disabled} onClick={() => void review(false, [item])}>{ui('analysis.reject')}</Button>
      </article>)}
    </section>
  </div>
}
