import {useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent} from 'react'
import {useParams} from 'react-router-dom'
import {Calculator, Download, Plus, RefreshCw, Save, ScanLine, Trash2, Upload} from 'lucide-react'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {Select, useDraftInput} from '../components/FormControls'
import {Empty, ErrorBox, Loading, PageTitle} from '../components/ui'
import {editableShip, highestShips, type MindCalculation, type MindCatalog, type MindReport, type MindShip, type Rarity} from '../mind/types'
import '../mind/mind.css'

const rarities: Rarity[] = ['UR', 'SSR', 'SR', 'R', 'N']
const bands = ['≤100', '101–105', '106–110', '111–115', '116–119', '≥120']
const number = (value: number) => value.toLocaleString()
function ShipLevel({value, label, disabled, onCommit}: {value: number; label: string; disabled: boolean; onCommit: (level: number) => void}) {
  const draft = useDraftInput(String(value), text => {
    const level = Number(text)
    if (text.trim() && Number.isInteger(level) && level >= 1 && level <= 125) onCommit(level)
  })
  return <input type="number" min={1} max={125} step={1} aria-label={label} disabled={disabled} {...draft}/>
}
function fileContent(file: File) {
  if (file.size > 5_500_000) throw new Error('文件超过 5.5 MB 限制')
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(new Error('无法读取文件'))
    reader.readAsDataURL(file)
  })
}
function download(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(content), char => char.charCodeAt(0))]))
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function MindCalculator() {
  const {instance = ''} = useParams(), {ui, instances, notify} = useApp(), connection = useConnection()
  const [catalog, setCatalog] = useState<MindCatalog>(), [saved, setSaved] = useState<MindReport>()
  const [ships, setShips] = useState<MindShip[]>([]), [result, setResult] = useState<MindCalculation>()
  const calculatedShips = useRef<MindShip[]>([])
  const [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [autoSave, setAutoSave] = useState(false), editVersion = useRef(0)
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all'), [page, setPage] = useState(0)
  const [filterMin, setFilterMin] = useState(''), [filterMax, setFilterMax] = useState(''), [filterRarity, setFilterRarity] = useState('')
  const [name, setName] = useState(''), [level, setLevel] = useState('100'), [rarity, setRarity] = useState<Rarity | ''>('')
  const [exportFormat, setExportFormat] = useState<'xlsx' | 'csv' | 'json'>('xlsx')
  const [scanMin, setScanMin] = useState('95'), [scanMax, setScanMax] = useState('120')
  const [progress, setProgress] = useState('')
  const dirtyRef = useRef(false), savedRef = useRef<MindReport | undefined>(undefined), requestVersion = useRef(0), alive = useRef(true)
  const draftKey = `azurpilot.mind-draft.${instance}`
  const current = instances.find(item => item.name === instance)
  const running = current?.status === 'running'
  const scanning = running && current?.currentTask === 'MindCalculatorScan'
  const ready = connection === 'ready' && !!saved
  const scanReason = connection !== 'ready' ? ui('mind.scanDisconnected')
    : !saved || !current ? ui('mind.scanLoading')
    : busy ? ui('mind.processing')
    : scanning ? ui('mind.scanInProgress')
    : running ? ui('mind.scanRunning')
    : current.status === 'updating' ? ui('mind.scanUpdating')
    : current.region && current.region !== 'cn' ? ui('mind.scanUnsupported')
    : dirty ? ui('mind.scanDraft') : ''
  function accept(report: MindReport, resetPage = true) {
    savedRef.current = report
    const next = report.ships.map(editableShip)
    calculatedShips.current = next
    setSaved(report); setShips(next); setResult(report)
    setScanMin(String(report.min_level ?? 95)); setScanMax(String(report.max_level ?? 120))
    dirtyRef.current = false; setDirty(false)
    if (resetPage) setPage(0)
    setAutoSave(false)
    try {sessionStorage.removeItem(draftKey)} catch { /* 浏览器禁用存储时仍可编辑。 */ }
  }
  useEffect(() => {
    alive.current = true
    return () => {alive.current = false}
  }, [])
  useEffect(() => {
    if (!scanning || connection !== 'ready') return
    let active = true, cursor = 0
    const readProgress = async () => {
      try {
        const logs = await api.request('logs.get', {instance, after: cursor})
        cursor = logs.cursor
        const latest = logs.entries.filter(entry => entry.text.includes('[心智扫描]')).at(-1)
        if (active && latest) setProgress(latest.text)
      } catch { /* 任务状态由公共连接和实例订阅处理。 */ }
    }
    void readProgress()
    const timer = setInterval(() => void readProgress(), 3000)
    return () => {active = false; clearInterval(timer)}
  }, [scanning, connection, instance])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    Promise.all([api.request('mind.catalog', {instance}), api.request('mind.report', {instance})])
      .then(([data, report]) => {if (active) {
        setCatalog(data)
        if (!savedRef.current) {
          setScanMin(String(report.min_level ?? 95)); setScanMax(String(report.max_level ?? 120))
          try {
            const draft = JSON.parse(sessionStorage.getItem(draftKey) ?? 'null') as {revision: string; ships: MindShip[]} | null
            if (draft && typeof draft.revision === 'string' && Array.isArray(draft.ships) && draft.ships.length <= 5000 &&
              draft.ships.every(ship => ship && typeof ship.name === 'string' && Number.isInteger(ship.level) && ship.level >= 0 && ship.level <= 125)) {
              const recovered = {...report, revision: draft.revision}
              savedRef.current = recovered; setSaved(recovered); setShips(draft.ships.map(editableShip))
              dirtyRef.current = true; setDirty(true); return
            }
          } catch { /* 不读取损坏的草稿。 */ }
        }
        if (!dirtyRef.current) accept(report)
      }})
      .catch(error => {if (active) setError(error.message)})
    const timer = setInterval(() => {
      if (dirtyRef.current) return
      void api.request('mind.report', {instance}).then(report => {
        if (active && !dirtyRef.current) {
          if (savedRef.current?.revision !== report.revision) {
            savedRef.current = report; setSaved(report)
            const next = report.ships.map(editableShip)
            calculatedShips.current = next
            setShips(next); setResult(report)
          }
        }
      }).catch(error => {if (active) setError(error.message)})
    }, 5000)
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection])
  useEffect(() => {
    if (!dirty || connection !== 'ready') return
    const version = ++requestVersion.current
    const timer = setTimeout(() => {
      void api.request('mind.calculate', {instance, ships}).then(value => {
        if (alive.current && dirtyRef.current && requestVersion.current === version) {
          calculatedShips.current = ships
          setResult(value)
        }
      }).catch(error => {if (alive.current && requestVersion.current === version) setError(error.message)})
    }, 250)
    return () => {clearTimeout(timer); requestVersion.current++}
  }, [ships, dirty, connection, instance])
  useEffect(() => {
    if (!autoSave || !dirty || connection !== 'ready' || busy || running) return
    const version = editVersion.current
    const timer = setTimeout(() => {
      setBusy(true); setError('')
      let submittedDraft: string | null = null
      try {
        const draft = sessionStorage.getItem(draftKey)
        if (draft && JSON.stringify(JSON.parse(draft).ships) === JSON.stringify(ships)) submittedDraft = draft
      } catch { /* 存储不可用时仍可保存到实例。 */ }
      void api.request('mind.save', {instance, revision: savedRef.current!.revision, ships}).then(report => {
        // 切换页面后响应仍可能成功；只清除本次提交对应的草稿，不能删除后来编辑的新草稿。
        try {
          if (submittedDraft && sessionStorage.getItem(draftKey) === submittedDraft) sessionStorage.removeItem(draftKey)
        } catch { /* 不让浏览器存储限制影响已成功的保存。 */ }
        if (!alive.current) return
        savedRef.current = report; setSaved(report)
        if (editVersion.current === version) accept(report, false)
      }).catch(error => {
        if (alive.current) {setError(error.message); setAutoSave(false)}
      }).finally(() => {if (alive.current) setBusy(false)})
    }, 500)
    return () => clearTimeout(timer)
  }, [ships, autoSave, dirty, connection, busy, running, instance])
  function edit(next: MindShip[], saveAutomatically = false) {
    editVersion.current++
    requestVersion.current++
    setAutoSave(saveAutomatically)
    setShips(next); setDirty(true); dirtyRef.current = true; setError('')
    try {sessionStorage.setItem(draftKey, JSON.stringify({revision: savedRef.current?.revision, ships: next}))} catch { /* 容量不足不阻止编辑。 */ }
  }
  function change(index: number, patch: Partial<MindShip>, saveAutomatically = false) {
    edit(ships.map((ship, i) => i === index ? {...ship, ...patch} : ship), saveAutomatically)
  }
  async function action(work: () => Promise<void>) {
    setBusy(true); setError('')
    try {await work()} catch (error) {if (alive.current) setError((error as Error).message)}
    finally {if (alive.current) setBusy(false)}
  }
  async function upload(event: ChangeEvent<HTMLInputElement>, screenshots: boolean) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!files.length) return
    await action(async () => {
      const added: MindShip[] = []
      const failures: string[] = []
      for (const file of files) {
        setProgress(ui('mind.importProgress', {current: files.indexOf(file) + 1, total: files.length, file: file.name}))
        try {
          const response = await api.request(screenshots ? 'mind.recognize' : 'mind.import', {instance, filename: file.name, content: await fileContent(file)})
          added.push(...response.ships.map(editableShip))
        } catch (error) {failures.push(`${file.name}: ${(error as Error).message}`)}
      }
      if (!alive.current) return
      if (!added.length && failures.length) throw new Error(failures.join('\n'))
      const next = highestShips([...ships, ...added], catalog?.ships)
      if (next.length > 5000) throw new Error(ui('mind.tooMany'))
      edit(next); setFilter('all'); setPage(0)
      setProgress(ui('mind.importComplete', {count: added.length, total: next.length}))
      if (failures.length) setError(failures.join('\n'))
    })
  }
  function add(event: FormEvent) {
    event.preventDefault()
    const info = catalog?.ships.find(ship => ship.name === name.trim())
    const baseRarity = rarity || info?.base_rarity
    if (!baseRarity) {setError(ui('mind.chooseRarity')); return}
    edit(highestShips([...ships, editableShip({name: name.trim(), level: Number(level), rarity: info?.rarity ?? baseRarity, base_rarity: baseRarity})], catalog?.ships))
    setName(''); setFilter('all'); setPage(Math.floor(ships.length / 50))
  }
  const rows = useMemo(() => ships.map((ship, index) => ({ship, index, row: calculatedShips.current[index] === ship ? result?.ships[index] : undefined})).filter(({ship, row}) =>
    ship.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (filter === 'all' || row?.status === filter) &&
    (!filterMin || ship.level >= Number(filterMin)) && (!filterMax || ship.level <= Number(filterMax)) &&
    (!filterRarity || row?.base_rarity === filterRarity)), [ships, result, filter, query, filterMin, filterMax, filterRarity])
  const pages = Math.max(1, Math.ceil(rows.length / 50))
  const currentPage = Math.min(page, pages - 1)
  const visible = rows.slice(currentPage * 50, (currentPage + 1) * 50)
  const labels = (value: Rarity) => ui(`mind.rarity.${value}`)
  return <div className="mind-calculator">
    <PageTitle title={ui('mind.title')} actions={<>
      <button className="button secondary" disabled={busy || !ready} onClick={() => action(async () => {accept(await api.request('mind.report', {instance}))})}><RefreshCw size={15}/>{ui(dirty ? 'mind.discard' : 'mind.reload')}</button>
      <button className="button primary" disabled={!dirty || busy || !ready || running} onClick={() => action(async () => {
        const report = await api.request('mind.save', {instance, revision: saved!.revision, ships})
        if (alive.current) {accept(report); notify(ui('mind.saved'))}
      })}><Save size={15}/>{ui('mind.save')}</button>
    </>}/>
    <section className="mind-panel mind-intro"><Calculator size={26}/><div><p>{ui('mind.hint')}</p><small className="muted">{ui('mind.catalogDate', {date: catalog?.updated_at.split('T')[0] ?? '—'})} · {ui(dirty ? autoSave ? 'mind.levelSaving' : 'mind.unsaved' : 'mind.savedState')}</small></div></section>
    {error && <ErrorBox message={error}/>}
    {!saved && !error && <Loading/>}
    {saved && <>
      <section className="mind-panel mind-toolbar" aria-busy={busy}>
        <label>{ui('mind.minLevel')}<input className="mind-range" type="number" min={1} max={125} step={1} value={scanMin} disabled={busy || running} onChange={event => setScanMin(event.target.value)}/></label>
        <label>{ui('mind.maxLevel')}<input className="mind-range" type="number" min={1} max={125} step={1} value={scanMax} disabled={busy || running} onChange={event => setScanMax(event.target.value)}/></label>
        <button className="button secondary" disabled={!!scanReason} title={scanReason || undefined} aria-describedby={scanReason ? 'mind-scan-reason' : 'mind-scan-hint'} onClick={() => action(async () => {
          const min = Number(scanMin), max = Number(scanMax)
          if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max > 125 || min > max) throw new Error(ui('mind.invalidRange'))
          const config = await api.request('config.get', {instance})
          await api.request('config.patch', {instance, revision: config.revision, changes: [
            {path: 'MindCalculatorScan.MindCalculator.MinLevel', value: min}, {path: 'MindCalculatorScan.MindCalculator.MaxLevel', value: max},
          ]})
          await api.request('tasks.run', {instance, task: 'MindCalculatorScan'}); notify(ui('mind.scanStarted'))
        })}><ScanLine size={16}/>{ui(scanning ? 'mind.scanning' : 'mind.scan')}</button>
        {scanning && <button className="button secondary" disabled={busy} onClick={() => action(async () => {await api.request('scheduler.stop', {instance})})}>{ui('mind.stop')}</button>}
        <label className={`button secondary file-button${busy || !ready ? ' mind-disabled' : ''}`}><Upload size={16}/>{ui('mind.import')}<input type="file" accept=".json,.csv,.xlsx" disabled={busy || !ready} onChange={event => upload(event, false)}/></label>
        <label className={`button secondary file-button${busy || !ready ? ' mind-disabled' : ''}`}><ScanLine size={16}/>{ui('mind.screenshots')}<input type="file" multiple accept="image/png,image/jpeg,image/webp" disabled={busy || !ready} onChange={event => upload(event, true)}/></label>
        <div className="mind-export"><Select aria-label={ui('mind.exportFormat')} value={exportFormat} onChange={event => setExportFormat(event.target.value as typeof exportFormat)}><option value="xlsx">Excel</option><option value="csv">CSV</option><option value="json">JSON</option></Select><button className="button secondary" disabled={busy || dirty || !ready} onClick={() => action(async () => {const file = await api.request('mind.export', {instance, format: exportFormat}); download(file.filename, file.content)})}><Download size={16}/>{ui('mind.export')}</button></div>
        {scanReason && <p id="mind-scan-reason" role="status"><strong>{scanReason}</strong></p>}
        <p id="mind-scan-hint" className="muted">{ui('mind.scanHint')}</p>
        {progress && <p className="muted" role="status">{progress}</p>}
      </section>
      <div className="mind-totals" aria-live="polite">
        <div className="mind-panel"><span>{ui('mind.mind')}</span><strong>{number(result?.mind ?? 0)}</strong></div>
        <div className="mind-panel"><span>{ui('mind.gold')}</span><strong>{number(result?.gold ?? 0)}</strong></div>
        <div className="mind-panel"><span>{ui('mind.included')}</span><strong>{number(result?.included ?? 0)}</strong><small>{ui('mind.mergedCount', {count: result?.merged ?? 0})}</small></div>
        <button className="mind-panel" onClick={() => {setFilter('review'); setPage(0)}}><span>{ui('mind.review')}</span><strong>{number(result?.review ?? 0)}</strong><small>{ui('mind.reviewHint')}</small></button>
      </div>
      <section className="mind-panel"><h2>{ui('mind.summary')}</h2><div className="mind-table-wrap"><table><thead><tr><th>{ui('mind.rarity')}</th>{bands.map(band => <th key={band}>{band}</th>)}<th>{ui('mind.mind')}</th><th>{ui('mind.gold')}</th></tr></thead><tbody>{result?.summary.map(row => <tr key={row.rarity}><th><span className={`mind-rarity rarity-${row.rarity}`}>{labels(row.rarity)}</span></th>{row.stages.map((count, i) => <td key={i}>{number(count)}</td>)}<td>{number(row.mind)}</td><td>{number(row.gold)}</td></tr>)}</tbody></table></div></section>
      <section className="mind-panel">
        <h2>{ui('mind.ships')}</h2>
        <p className="muted">{ui('mind.levelEditHint')}</p>
        <form className="mind-add" onSubmit={add}>
          <label>{ui('mind.name')}<input list="mind-ship-catalog" required maxLength={100} value={name} onChange={event => setName(event.target.value)}/></label>
          <datalist id="mind-ship-catalog">{catalog?.ships.map(ship => <option key={ship.name} value={ship.name}>{labels(ship.base_rarity)}</option>)}</datalist>
          <label>{ui('mind.level')}<input type="number" required min={1} max={125} step={1} value={level} onChange={event => setLevel(event.target.value)}/></label>
          <label>{ui('mind.baseRarity')}<Select aria-label={ui('mind.baseRarity')} value={rarity} onChange={event => setRarity(event.target.value as Rarity | '')}><option value="">{ui('mind.autoRarity')}</option>{rarities.map(r => <option key={r} value={r}>{labels(r)}</option>)}</Select></label>
          <button className="button secondary" disabled={busy || !ready || ships.length >= 5000}><Plus size={16}/>{ui('mind.add')}</button>
        </form>
        <div className="mind-filters"><input aria-label={ui('mind.search')} placeholder={ui('mind.search')} value={query} onChange={event => {setQuery(event.target.value); setPage(0)}}/>
          <label>{ui('mind.filterMin')}<input type="number" min={1} max={125} step={1} value={filterMin} onChange={event => {setFilterMin(event.target.value); setPage(0)}}/></label>
          <label>{ui('mind.filterMax')}<input type="number" min={1} max={125} step={1} value={filterMax} onChange={event => {setFilterMax(event.target.value); setPage(0)}}/></label>
          <Select aria-label={ui('mind.filterRarity')} value={filterRarity} onChange={event => {setFilterRarity(event.target.value); setPage(0)}}><option value="">{ui('mind.allRarities')}</option>{rarities.map(value => <option key={value} value={value}>{labels(value)}</option>)}</Select>
          <Select aria-label={ui('mind.filter')} value={filter} onChange={event => {setFilter(event.target.value); setPage(0)}}>{(['all', 'included', 'review', 'merged', 'excluded'] as const).map(status => <option key={status} value={status}>{ui(`mind.${status}`)}</option>)}</Select><span className="muted">{ui('mind.rowCount', {count: rows.length})}</span></div>
        {visible.length ? <div className="mind-table-wrap"><table className="mind-ship-table"><thead><tr><th>{ui('mind.name')}</th><th>{ui('mind.level')}</th><th>{ui('mind.baseRarity')}</th><th>{ui('mind.status')}</th><th>{ui('mind.mind')}</th><th>{ui('mind.actions')}</th></tr></thead><tbody>{visible.map(({ship, index, row}) => <tr key={`${index}:${ship.name}`}>
          <td><input aria-label={`${ui('mind.name')} ${index + 1}`} value={ship.name} readOnly/><small className="muted" title={ship.source}>{ship.source}</small></td>
          <td><ShipLevel label={`${ui('mind.level')} ${index + 1}`} value={ship.level} disabled={busy || running} onCommit={value => change(index, {level: value}, true)}/></td>
          <td><span className={`mind-rarity rarity-${row?.base_rarity}`}>{row?.base_rarity ? labels(row.base_rarity) : '—'}</span></td>
          <td><Select aria-label={`${ui('mind.status')} ${index + 1}`} className={`mind-status status-${row?.status}`} value={row?.status ?? 'review'} disabled={busy || running || !row || row.automatic_excluded} title={row?.automatic_excluded ? ui('mind.autoExcluded') : undefined} onChange={event => change(index, {excluded: event.target.value === 'excluded', review: event.target.value === 'review'}, true)}>
            <option value="included" disabled={!ship.level || !row?.base_rarity}>{ui('mind.included')}</option><option value="review">{ui('mind.review')}</option><option value="excluded">{ui('mind.excluded')}</option>{row?.status === 'merged' && <option value="merged" disabled>{ui('mind.merged')}</option>}
          </Select></td><td>{number(row?.mind ?? 0)}</td>
          <td><button className="button secondary" aria-label={`${ui('mind.delete')} ${ship.name}`} disabled={busy || running} onClick={() => edit(ships.filter((_, i) => i !== index), true)}><Trash2 size={15}/>{ui('mind.delete')}</button></td>
        </tr>)}</tbody></table></div> : <Empty title={ui('mind.empty')}>{ui('mind.emptyHint')}</Empty>}
        <div className="mind-pagination"><button className="button secondary" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{ui('mind.previous')}</button><span>{currentPage + 1} / {pages}</span><button className="button secondary" disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>{ui('mind.next')}</button></div>
      </section>
    </>}
  </div>
}
