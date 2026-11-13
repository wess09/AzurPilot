/**
 * @fileoverview 船坞台账页：浏览并就地修订已确认的舰船报告，以 revision 乐观锁防覆盖，草稿按 instance 暂存 sessionStorage。
 */

import {Button} from '../components/ui/button'
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from '../components/ui/table'
import {FleetFilterRow, fleetRarities, ledgerShipTypes as shipTypes, ledgerTypeIds as typeIds} from '../fleet-tech/filters'
import {useEffect, useId, useMemo, useRef, useState} from 'react'
import {Link, useSearchParams} from 'react-router-dom'
import {api} from '../api/client'
import type {DockCard, DockReport} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, Loading} from '../components/ui'
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '../components/official-ui/select'
import {Checkbox as CheckboxControl} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {Input} from '../components/official-ui/input'
import type {CatalogShip, MindCatalog} from '../mind/types'
import type {UiKey} from '../i18n'
import {fleetFactionOrder, translateFleetTech} from '../fleet-tech/i18n'
import {useFleetPreference} from '../fleet-tech/preferences'
import '../fleet-tech/style.css'
import './fleet-ledger.css'

const rarities = fleetRarities.slice(0, 5)
const nationValue = (ship?: CatalogShip) => ship?.nationality == null ? ship?.nation ?? '' : String(ship.nationality)
const nationOrder = (value: string) => {const index = fleetFactionOrder.indexOf(Number(value)); return index < 0 ? fleetFactionOrder.length : index}
const normalizedName = (value: string) => value.normalize('NFKC').replace(/[\s.·・．。]/g, '').toLocaleLowerCase()
const sortColumns = ['code', 'name', 'level', 'breakthrough', 'type', 'nation', 'rarity', 'reviewFlag'] as const
type SortColumn = typeof sortColumns[number]
const sortLabels = {code: 'fleetTech.code', name: 'analysis.name', level: 'analysis.level', breakthrough: 'analysis.breakthrough', type: 'analysis.type', nation: 'analysis.nation', rarity: 'analysis.rarity', reviewFlag: 'analysis.reviewFlag'} as const satisfies Record<SortColumn, UiKey>
type Sort = {column: SortColumn; direction: 'ascending' | 'descending'}
type DraftCard = Omit<DockCard, 'level'> & {level: number | ''}
type Draft = {revision: string; ships: Record<number, DraftCard>; deleted: number[]}
type Changes = Parameters<typeof api.request<'dock.patch'>>[1]['changes']

/**
 * 船坞台账页：以 revision 为乐观锁就地编辑已确认的舰船报告。
 *
 * 草稿按 instance 存 sessionStorage；report.revision 变旧（stale）后禁止保存，
 * 防止把扫描期间的新变更覆盖掉。
 *
 * @param report 最近一次确认的船坞报告，为空时只渲染加载/错误占位。
 * @param onBusy 保存进行中回调 true/false，外层据此锁全局操作。
 */
export function FleetLedger({instance, report, onReport, onBusy, locked = false}: {
  instance: string; report?: DockReport; locked?: boolean; onReport: (report: DockReport) => void
  onBusy: (busy: boolean) => void
}) {
  const alive = useRef(true), list = useId(), table = useRef<HTMLDivElement>(null), focusedShip = useRef('')
  useEffect(() => {alive.current = true; return () => {alive.current = false}}, [])
  const {ui, language} = useApp(), connection = useConnection(), [params, setParams] = useSearchParams()
  const [catalog, setCatalog] = useState<MindCatalog>(), [error, setError] = useState(''), [busy, setBusy] = useState(false), [saved, setSaved] = useState(false)
  const storageKey = `azurpilot.fleet-ledger.v1.${instance}`
  const [draft, setDraft] = useState<Draft | null>(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')
      return value && typeof value.revision === 'string' && value.ships && Array.isArray(value.deleted) ? value : null
    } catch { /* 草稿损坏时当作没有草稿。 */ return null }
  })
  const dirty = !!draft && (!!Object.keys(draft.ships).length || !!draft.deleted.length)
  const stale = dirty && !!report && draft.revision !== report.revision
  // 未保存草稿存进 sessionStorage，刷新后可恢复；这是尽力而为的附加功能。
  useEffect(() => {
    try {if (dirty) sessionStorage.setItem(storageKey, JSON.stringify(draft)); else sessionStorage.removeItem(storageKey)} catch { /* sessionStorage 被禁时写入会抛错：丢草稿可接受，页面不能崩。 */ }
  }, [draft, dirty, storageKey])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {if (dirty) {event.preventDefault(); event.returnValue = ''}}
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  const groupFilter = params.get('group'), shipFilter = params.get('ship')
  const [query, setQuery] = useFleetPreference<string>(instance, 'ledger.query', ''), [filters, setFilters] = useFleetPreference<Record<string, string[]>>(instance, 'ledger.filters', {})
  const [minimum, setMinimum] = useFleetPreference<string>(instance, 'ledger.minimum', ''), [maximum, setMaximum] = useFleetPreference<string>(instance, 'ledger.maximum', '')
  const [sort, setSort] = useFleetPreference<Sort>(instance, 'ledger.sort', {column: 'code', direction: 'ascending'})
  const [batch, setBatch] = useState(false), [selected, setSelected] = useState<number[]>([])
  useEffect(() => {
    let active = true
    setCatalog(undefined)
    if (connection === 'ready') void api.request('mind.catalog', {instance}).then(value => {if (active) setCatalog(value)}).catch(e => {if (active) setError((e as Error).message)})
    return () => {active = false}
  }, [instance, connection])
  const tr = (key: string) => translateFleetTech(language, key)
  const typeName = (value: string) => value === '导驱' ? value : typeIds[value] ? tr(`type.${typeIds[value]}`) : value
  const catalogIndex = useMemo(() => {
    const exact = new Map<string, CatalogShip>(), base = new Map<number, CatalogShip>()
    for (const ship of catalog?.ships ?? []) {
      const key = `${ship.group_type}:${ship.name}`
      if (!exact.has(key)) exact.set(key, ship)
      if (ship.group_type != null && ship.group !== '改造' && !base.has(ship.group_type)) base.set(ship.group_type, ship)
    }
    return {exact, base}
  }, [catalog])
  const infoFor = (row: Pick<DockCard, 'name' | 'group_type'>) => catalogIndex.exact.get(`${row.group_type}:${row.name}`)
    ?? (row.group_type == null ? undefined : catalogIndex.base.get(row.group_type))
  const nationName = (value: string) => {
    const key = `nation.${value}`, label = translateFleetTech(language, key)
    return label === key ? value : label
  }
  const nations = [...new Set(catalog?.ships.map(nationValue).filter(Boolean))]
    .sort((a, b) => nationOrder(a) - nationOrder(b) || a.localeCompare(b))
  const counts = new Map<string, number>()
  for (const row of report?.ships ?? []) {const key = String(row.group_type ?? row.name); counts.set(key, (counts.get(key) ?? 0) + 1)}
  // 打字时已确认的行保持原位：即使这次编辑让它不再命中当前筛选，也不把它从列表里抽走，免得整表跳动。
  const rows = useMemo(() => {
    const counts = new Map<string, number>()
    const shipInfo = new Map<number, CatalogShip | undefined>()
    for (const row of report?.ships ?? []) {const key = String(row.group_type ?? row.name); counts.set(key, (counts.get(key) ?? 0) + 1)}
    const result = (report?.ships ?? []).filter(row => {
      const ship = infoFor(row)
      shipInfo.set(row.id, ship)
      const statuses = [
        ...(row.level > 0 && row.level < 120 ? ['unfinished'] : []),
        ...(row.level >= 120 ? ['lv120'] : []),
        ...(row.full_star === false ? ['missingStar'] : row.full_star === true ? ['fullStar'] : []),
      ]
      const records = [
        ...(row.review || row.group_type === null ? ['review'] : []),
        ...((counts.get(String(row.group_type ?? row.name)) ?? 0) > 1 ? ['duplicates'] : []),
        ...(row.level === 0 ? ['missingLevel'] : []),
        ...(row.full_star == null ? ['unknownStar'] : []),
      ]
      const matches = (key: string, values: string[]) => {
        const selected = (filters[key] ?? []).filter(value => key !== 'records' || value !== 'unique')
        return !selected.length || selected.some(value => values.includes(value))
      }
      return String(row.id) === shipFilter || (!groupFilter || row.group_type === Number(groupFilter)) && (row.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()) || String(row.id) === query)
        && (!minimum || row.level >= Number(minimum)) && (!maximum || row.level <= Number(maximum))
        && matches('nation', [nationValue(ship)]) && matches('type', [ship?.type ?? ''])
        && matches('rarity', [row.rarity]) && matches('status', statuses) && matches('records', records)
    })
    const representatives = new Map<number, DockCard>()
    if (filters.records?.includes('unique')) for (const row of result) {
      if (row.group_type == null) continue
      const previous = representatives.get(row.group_type)
      if (!previous || String(row.id) === shipFilter || String(previous.id) !== shipFilter
          && (row.level > previous.level || row.level === previous.level
            && (row.form === 'retrofit' && previous.form !== 'retrofit'
              || (row.form === 'retrofit') === (previous.form === 'retrofit') && row.id < previous.id))) representatives.set(row.group_type, row)
    }
    const visible = filters.records?.includes('unique') ? result.filter(row => row.group_type == null || representatives.get(row.group_type)?.id === row.id) : result
    const collator = new Intl.Collator(language, {numeric: true})
    function sortValue(row: DockCard): string | number | null {
      const ship = shipInfo.get(row.id)
      switch (sort.column) {
        case 'code': return ship?.code ?? null
        case 'name': return row.name
        case 'level': return row.level || null
        case 'breakthrough': return row.full_star == null ? null : Number(row.full_star)
        case 'type': return ship?.type ? shipTypes.indexOf(ship.type) : null
        case 'nation': return nationValue(ship) ? nationOrder(nationValue(ship)) : null
        case 'rarity': return row.rarity ? rarities.indexOf(row.rarity) : null
        case 'reviewFlag': return row.review || !row.group_type ? 2 : row.level === 0 ? 1 : 0
      }
    }
    return visible.sort((a, b) => {
      const left = sortValue(a), right = sortValue(b)
      if (left === null && right !== null) return 1
      if (right === null && left !== null) return -1
      const difference = (typeof left === 'number' && typeof right === 'number' ? left - right
        : typeof left === 'string' && typeof right === 'string' ? collator.compare(left, right) : 0
      ) || (sort.column === 'nation' ? collator.compare(nationName(nationValue(shipInfo.get(a.id))), nationName(nationValue(shipInfo.get(b.id)))) : 0)
      return difference * (sort.direction === 'ascending' ? 1 : -1)
        || collator.compare(a.name, b.name) || a.id - b.id
    })
  }, [report?.ships, catalogIndex, query, minimum, maximum, filters, sort, groupFilter, shipFilter, language])
  const additions = Object.values(draft?.ships ?? {}).filter(row => row.id < 0)
  const displayRows: DraftCard[] = [...additions, ...rows]
  useEffect(() => {
    table.current?.scrollTo?.({top: 0})
  }, [query, filters, minimum, maximum, sort, groupFilter])
  useEffect(() => {
    if (!shipFilter || focusedShip.current === shipFilter || !report || !catalog) return
    const target = document.getElementById(`ledger-ship-${shipFilter}`)
    if (target) {target.scrollIntoView?.({block: 'nearest'}); focusedShip.current = shipFilter}
  }, [shipFilter, report, catalog])
  function sortBy(column: SortColumn) {
    setSort(current => ({column, direction: current.column === column
      ? current.direction === 'ascending' ? 'descending' : 'ascending'
      : column === 'level' || column === 'rarity' ? 'descending' : 'ascending'}))
  }
  const disabled = locked || busy || connection !== 'ready' || !report
  function change(row: DraftCard, values: Partial<DraftCard>) {
    if (disabled || !report) return
    setSaved(false)
    setDraft(current => {
      const ships = {...current?.ships}, deleted = current?.deleted ?? []
      const next = {...row, ...current?.ships[row.id], ...values}
      const original = report.ships.find(ship => ship.id === row.id)
      if (original && (['name', 'group_type', 'level', 'rarity', 'base_rarity', 'full_star', 'form', 'review'] as const)
        .every(key => (next[key] ?? null) === (original[key] ?? null))) delete ships[row.id]
      else ships[row.id] = next
      return Object.keys(ships).length || deleted.length ? {revision: current?.revision ?? report.revision, ships, deleted} : null
    })
  }
  function rename(row: DraftCard, name: string) {
    const matches = catalog?.ships.filter(info => info.name === name) ?? []
    const info = matches.length === 1 ? matches[0] : undefined
    change(row, {name, group_type: info?.group_type ?? null, rarity: info?.rarity ?? row.rarity,
      base_rarity: info?.base_rarity ?? row.base_rarity, form: info ? info.group === '改造' ? 'retrofit' : 'base' : null, review: !info})
  }
  function identityCandidates(row: DraftCard) {
    const name = normalizedName(row.name)
    return (catalog?.ships ?? []).filter(ship => normalizedName(ship.name) === name || normalizedName(ship.raw_name ?? ship.name) === name)
  }
  function identify(row: DraftCard, info: CatalogShip) {
    setError('')
    change(row, {name: info.name, group_type: info.group_type ?? null, rarity: info.rarity, base_rarity: info.base_rarity,
      form: info.group === '改造' ? 'retrofit' : 'base', review: false})
  }
  function setReview(row: DraftCard, review: boolean) {
    if (!review && !row.group_type) {
      const candidates = identityCandidates(row)
      if (candidates.length === 1) identify(row, candidates[0]!)
      else setError(ui('analysis.identityRequired'))
    } else change(row, {review})
  }
  function add() {
    if (disabled || !report) return
    // 新增行用递减的负数 id：不会与真实舰船 id 相撞，保存时负数 id 不传服务端、由服务端分配。
    const id = Math.min(-1, ...Object.keys(draft?.ships ?? {}).map(Number)) - 1
    change({id, name: '', group_type: null, level: 1, rarity: 'N', base_rarity: 'N', extra_exp: null,
      full_star: null, form: null, review: true, source: 'manual'}, {})
    table.current?.scrollTo?.({top: 0})
  }
  function remove(row: DraftCard) {
    if (disabled || !report) return
    setSaved(false)
    setDraft(current => {
      const ships = {...current?.ships}, deleted = current?.deleted ?? []
      if (row.id < 0) delete ships[row.id]
      const nextDeleted = row.id < 0 ? deleted : deleted.includes(row.id) ? deleted.filter(id => id !== row.id) : [...deleted, row.id]
      return Object.keys(ships).length || nextDeleted.length ? {revision: current?.revision ?? report.revision, ships, deleted: nextDeleted} : null
    })
  }
  function discard() {setDraft(null); setError(''); setSaved(false); setSelected([])}
  async function save() {
    if (!report || !draft || !dirty || disabled || stale) return
    const changes: Changes = []
    for (const row of Object.values(draft.ships)) {
      if (draft.deleted.includes(row.id)) continue
      if (!row.name.trim() || row.name.length > 100 || row.level === '' || !Number.isInteger(row.level) || row.level < 0 || row.level > 125) {setError(ui('analysis.inlineInvalid')); return}
      changes.push({id: row.id > 0 ? row.id : undefined, name: row.name, group_type: row.group_type, level: row.level,
        rarity: row.rarity as Changes[number]['rarity'], base_rarity: row.base_rarity as Changes[number]['base_rarity'],
        full_star: row.full_star ?? null, form: row.form ?? null, review: row.review,
        ...(row.id < 0 ? {extra_exp: null, source: 'manual'} : {})})
    }
    changes.push(...draft.deleted.map(id => ({id, delete: true})))
    setBusy(true); onBusy(true); setError('')
    try {
      const value = await api.request('dock.patch', {instance, revision: draft.revision, changes})
      if (alive.current) {onReport(value); setDraft(null); setSelected([]); setSaved(true)}
    } catch (e) {if (alive.current) setError((e as Error).message)}
    finally {if (alive.current) {setBusy(false); onBusy(false)}}
  }
  function filterGroup(key: string, label: string, options: [string, string][]) {
    return <FleetFilterRow filter={key} label={label} options={options} filters={filters} setFilters={setFilters} all={tr('all')}/>
  }
  const changedCount = new Set([...Object.keys(draft?.ships ?? {}).map(Number), ...draft?.deleted ?? []]).size
  if (!report || !catalog) return error ? <ErrorBox message={error}/> : <Loading/>
  return <div className="fleet-ledger fleet-technology">
    {error && <ErrorBox message={error}/>}
    <div className="ft-toolbar ledger-summary" role="status"><strong>{ui('analysis.confirmedCount')}: {report?.ships.length ?? 0}</strong><span>{ui('analysis.species')}: {counts.size}</span><span>{ui('analysis.needsReview')}: {report?.ships.filter(row => row.review || !row.group_type).length ?? 0}</span><span>{ui('analysis.time')}: {report?.updated_at || '—'}</span></div>
    {groupFilter && <p>{ui('analysis.filter')}: {report?.ships.find(row => row.group_type === Number(groupFilter))?.name || groupFilter} <Button variant="outline" onClick={() => {const next = new URLSearchParams(params); next.delete('group'); setParams(next, {replace: true})}}>{ui('analysis.all')}</Button></p>}
    <section className="ft-filters" aria-label={ui('analysis.filter')}>
      {filterGroup('type', tr('category'), shipTypes.filter(value => catalog?.ships.some(ship => ship.type === value)).map(value => [value, typeName(value)]))}
      {filterGroup('rarity', tr('rarity'), rarities.map(value => [value, tr(`rarity.${value}`)]))}
      {filterGroup('nation', tr('nation'), nations.map(value => [value, nationName(value)]))}
      {filterGroup('status', tr('status'), [['unfinished', tr('unfinished')], ['missingStar', tr('missingStar')], ['fullStar', ui('analysis.fullStarYes')], ['lv120', 'Lv.120+']])}
      {filterGroup('records', ui('analysis.filter'), [['review', ui('analysis.needsReview')], ['duplicates', ui('analysis.duplicates')], ['missingLevel', ui('analysis.missing')], ['unknownStar', `${ui('analysis.breakthrough')} · ${ui('analysis.unknownValue')}`], ['unique', ui('analysis.uniqueShips')]])}
      <div className="ft-filter-row"><strong>{ui('analysis.level')}</strong><div className="ft-chips ledger-level-range"><label>{ui('analysis.min')}<Input type="number" min={0} max={125} value={minimum} onChange={e => setMinimum(e.target.value)}/></label><span>—</span><label>{ui('analysis.max')}<Input type="number" min={0} max={125} value={maximum} onChange={e => setMaximum(e.target.value)}/></label></div></div>
    </section>
    <div className="ft-toolbar ft-savebar">
      <Button disabled={disabled || !dirty || stale} onClick={() => void save()}>{ui('analysis.save')}</Button>
      {dirty && <><span role="status">{ui('analysis.unsavedChanges')}: {changedCount}</span><Button variant="outline" disabled={busy || locked} onClick={discard}>{ui('analysis.discard')}</Button></>}
      {saved && <span role="status">{ui('analysis.saved')}</span>}
      <Button variant="outline" disabled={disabled} onClick={add}>{ui('analysis.add')}</Button>
      <Button variant="outline" disabled={disabled} onClick={() => setParams({tab: 'scan'})}>{ui('analysis.scanPage')}</Button>
      {/* aria-disabled 挡不住 <Link> 的默认跳转，必须在 onClick 里手动 preventDefault */}
      {!!report?.pending_changes.length && <Link aria-disabled={disabled} onClick={event => {if (disabled) event.preventDefault()}} to="?tab=scan">{ui('analysis.pendingLink')} ({report.pending_changes.length})</Link>}
    </div>
    {stale && <p role="alert">{ui('analysis.stale')}</p>}
    <div className="ft-search"><Input type="search" aria-label={ui('analysis.search')} placeholder={ui('analysis.search')} value={query} onChange={e => setQuery(e.target.value)}/><span>{ui('mind.rowCount', {count: displayRows.length})}</span>
      <div className="ft-chips ledger-batch"><Button type="button" size="sm" variant={batch ? 'default' : 'outline'} disabled={disabled} aria-pressed={batch} onClick={() => {setBatch(!batch); setSelected([])}}>{ui('analysis.batch')}</Button>
      {batch && <Button type="button" size="sm" variant="outline" disabled={disabled || !selected.length} onClick={() => {for (const id of selected) {const row = draft?.ships[id] ?? report?.ships.find(row => row.id === id); if (row && !draft?.deleted.includes(id)) change(row, {review: true})}}}>{ui('analysis.batchReview')} ({selected.length})</Button>}</div>
    </div>
    <p className="ledger-hint">{ui('analysis.inlineHint')} {ui('analysis.fullStarRule')}</p>
    <datalist id={list}>{catalog?.ships.map(info => <option key={`${info.group_type}:${info.name}`} value={info.name}/>)}</datalist>
    <div className="ft-table-wrap ledger-table-wrap" ref={element => {table.current = element?.querySelector<HTMLDivElement>('[data-slot="table-container"]') ?? null}}><Table className="min-w-[1000px] whitespace-nowrap"><TableHeader className="sticky top-0 z-10"><TableRow>{batch && <TableHead scope="col" className="text-center">{ui('analysis.batch')}</TableHead>}{sortColumns.map(column => <TableHead key={column} scope="col" className="text-center" aria-sort={sort.column === column ? sort.direction : 'none'}><Button type="button" variant="ghost" size="sm" onClick={() => sortBy(column)}>{ui(sortLabels[column])}<span aria-hidden="true">{sort.column === column ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></Button></TableHead>)}<TableHead scope="col" className="text-center">{ui('analysis.delete')}</TableHead></TableRow></TableHeader><TableBody>{displayRows.map(original => {
      const row = draft?.ships[original.id] ?? original, deleted = draft?.deleted.includes(row.id), info = infoFor(row)
      const candidates = row.group_type == null ? identityCandidates(row) : []
      const label = (key: UiKey) => `${ui(key)} · ${row.name || ui('analysis.new')} #${row.id}`
      return <TableRow key={row.id} id={`ledger-ship-${row.id}`} data-state={shipFilter === String(row.id) ? 'selected' : undefined} className={[deleted ? 'ledger-deleted' : '', draft?.ships[row.id] ? 'ledger-modified' : '', shipFilter === String(row.id) ? 'ledger-highlight' : ''].filter(Boolean).join(' ')}>
        {batch && <TableCell className="text-center"><CheckboxControl disabled={disabled || deleted} aria-label={label('analysis.batch')} checked={selected.includes(row.id)} onCheckedChange={next => setSelected(next ? [...selected, row.id] : selected.filter(id => id !== row.id))}/></TableCell>}
        <TableCell className="text-center tabular-nums">{info?.code == null ? '—' : String(info.code).padStart(3, '0')}</TableCell>
        <TableCell className={`ft-name ft-rarity-${row.rarity}`}><Input list={list} aria-label={label('analysis.name')} maxLength={100} value={row.name} disabled={disabled || deleted || !catalog} onChange={e => rename(row, e.target.value)}/>{row.id > 0 && (counts.get(String(row.group_type ?? row.name)) ?? 0) > 1 && <small> · #{row.id}</small>}{row.id < 0 && <small> · {ui('analysis.new')}</small>}
          {candidates.length > 0 && <Select value="__choose__" disabled={disabled || deleted} onValueChange={value => {const info = candidates.find(ship => `${ship.group_type}:${ship.name}` === value); if (info) identify(row, info)}}><SelectTrigger aria-label={label('analysis.confirmIdentity')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__choose__">{ui('analysis.confirmIdentity')}</SelectItem>{candidates.map(ship => <SelectItem key={`${ship.group_type}:${ship.name}`} value={`${ship.group_type}:${ship.name}`}>{ship.raw_name ?? ship.name} · {nationName(nationValue(ship))} · {typeName(ship.type)} · {ship.code ?? ship.group_type}</SelectItem>)}</SelectContent></Select>}
        </TableCell>
        <TableCell><Input type="number" min={0} max={125} step={1} aria-label={label('analysis.level')} value={row.level} disabled={disabled || deleted} onChange={e => change(row, {level: e.target.value === '' ? '' : Number(e.target.value)})}/></TableCell>
        <TableCell><Select value={row.full_star == null ? '__unknown__' : String(row.full_star)} disabled={disabled || deleted} onValueChange={value => change(row, {full_star: value === '__unknown__' ? null : value === 'true'})}><SelectTrigger aria-label={label('analysis.breakthrough')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__unknown__">{ui('analysis.unknownValue')}</SelectItem><SelectItem value="false">{ui('analysis.fullStarNo')}</SelectItem><SelectItem value="true">{ui('analysis.fullStarYes')}</SelectItem></SelectContent></Select></TableCell>
        <TableCell className="text-center">{info?.type ? typeName(info.type) : '—'}</TableCell><TableCell className="text-center">{nationName(nationValue(info)) || '—'}</TableCell><TableCell className={`text-center ft-rarity-${row.rarity}`}>{row.rarity ? tr(`rarity.${row.rarity}`) : '—'}</TableCell>
        <TableCell><span className="flex items-center gap-3"><CheckboxControl id={`fleet-review-${row.id}`} aria-label={label('analysis.reviewFlag')} checked={row.review || !row.group_type} disabled={disabled || deleted} onCheckedChange={next => setReview(row, next === true)}/><Label htmlFor={`fleet-review-${row.id}`}>{ui(row.review || !row.group_type ? 'analysis.needsReview' : row.level === 0 || row.level === '' ? 'analysis.missing' : 'analysis.normal')}</Label></span></TableCell>
        <TableCell className="text-center"><Button variant="outline" disabled={disabled} onClick={() => remove(row)}>{ui(deleted ? 'analysis.restore' : 'analysis.delete')}</Button>{deleted && <small> {ui('analysis.deleted')}</small>}</TableCell>
      </TableRow>
    })}</TableBody></Table></div>
    {!displayRows.length && <p>{ui(report?.ships.length ? 'mind.empty' : 'analysis.emptyLedger')}</p>}
  </div>
}
