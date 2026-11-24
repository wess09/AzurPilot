/**
 * @fileoverview 养成计算页：汇总船坞报告、科技报告与图鉴，估算舰船 100→120 级的心智与黄币开销，并可生成自动培养方案。
 */

import {FleetFilterRow, fleetShipTypes as types, fleetAttributes as attrs, fleetRarities as rarities} from '../fleet-tech/filters'
import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {api, ApiError} from '../api/client'
import type {DockReport} from '../api/types'
import {catalogRows, matches, type Catalog, type Report} from '../fleet-tech/types'
import {fleetFactionOrder, translateFleetTech} from '../fleet-tech/i18n'
import {localeForLanguage} from '../i18n'
import {useFleetPreference} from '../fleet-tech/preferences'
import {useApp, useConnection} from '../app/context'
import {ErrorBox} from '../components/ui'
import {LoadBoundary} from '../components/ui/load-boundary'
import {usePageRead} from '../app/usePageRead'
import {Checkbox as CheckboxControl} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {Button} from '../components/ui/button'
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from '../components/ui/table'
import {Input} from '../components/official-ui/input'
import {automaticCandidates, readPlan, technologyEfficiency, type CultivationPlan, type CultivationReport} from '../mind/cultivation'
import '../fleet-tech/style.css'
import '../mind/cultivation.css'

const amount = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString()
const nationOrder = (value: number) => {const index = fleetFactionOrder.indexOf(value); return index < 0 ? fleetFactionOrder.length : index}
const columns = {name: 'ship', level: 'level', mind: 'units', gold: 'gold', efficiency: 'efficiency'} as const
type Column = keyof typeof columns
type Sort = {column: Column; direction: 'ascending' | 'descending'}
interface Facts {dock: DockReport; technology: Report; catalog: Catalog}
/**
 * 养成计算页：汇总船坞报告、科技报告与图鉴，估算每艘舰船 100→120 级的心智与黄币开销。
 *
 * 三类数据齐备才出结果；服务端返回 CONFLICT 时经 onRefresh 重取船坞快照再重算。
 *
 * @param report 共享的船坞确认报告，决定参与计算的舰船名单。
 * @param onRefresh 数据冲突时的回调，由外层重新拉取船坞报告。
 */
export function MindCalculator({report: dock, reportError, onRefresh, reloadRef}: {report?: DockReport; reportError?: string; onRefresh?: () => void; reloadRef?: {current: (() => void) | undefined}}) {
  const {instance = ''} = useParams(), connection = useConnection(), {language, ui} = useApp()
  const [facts, setFacts] = useState<Facts>(), [plan, setPlan] = useState<CultivationPlan>()
  const [query, setQuery] = useFleetPreference<string>(instance, 'mind.query', ''), [includedOnly, setIncludedOnly] = useFleetPreference<boolean>(instance, 'mind.includedOnly', false)
  const [filters, setFilters] = useFleetPreference<Record<string, string[]>>(instance, 'mind.filters', {}), [extra, setExtra] = useFleetPreference<boolean>(instance, 'mind.extra', false)
  const tr = (key: string) => translateFleetTech(language, key)
  const [sort, setSort] = useFleetPreference<Sort>(instance, 'mind.sort', {column: 'efficiency', direction: 'descending'})
  const loadCatalog = useCallback(() => api.request('fleetTech.catalog', {instance}), [instance])
  const catalogRead = usePageRead(instance, connection === 'ready', loadCatalog), catalog = catalogRead.data, catalogError = catalogRead.error
  const loadTechnology = useCallback(() => api.request('fleetTech.report', {instance}), [instance])
  const technologyRead = usePageRead(JSON.stringify([instance, dock?.revision]), connection === 'ready', loadTechnology)
  const technology = technologyRead.data, technologyError = technologyRead.error
  const refreshDock = useRef(onRefresh), refreshTechnology = useRef(technologyRead.reload)
  refreshDock.current = onRefresh; refreshTechnology.current = technologyRead.reload
  useEffect(() => {
    if (!reloadRef) return
    reloadRef.current = () => {technologyRead.reload(); if (catalogRead.error) catalogRead.reload()}
    return () => {reloadRef.current = undefined}
  }, [reloadRef, technologyRead.reload, catalogRead.reload, catalogRead.error])
  const memory = useRef<{instance: string; plan: CultivationPlan} | null>(null)
  const key = `azurpilot.cultivation-auto.${instance}`
  useEffect(() => {
    setFacts(undefined)
  }, [instance, connection])
  useEffect(() => {
    if (!dock || dock.instance !== instance || !catalog || !technology) return
    // 科技数据与共享船坞快照的到达顺序不定，版本对不上时本轮先不算，等下一次对齐。
    if (technology.data_version && technology.data_version !== dock.revision) return
    const previous = memory.current?.instance === instance ? memory.current.plan : undefined
    let stored: string | null = null
    if (!previous) try {stored = localStorage.getItem(key)} catch { /* localStorage 被禁时读不到历史计划，按默认重新计算即可。 */ }
    const next = readPlan(previous ? JSON.stringify(previous) : stored, dock.ships)
    if (!previous || JSON.stringify(previous) !== JSON.stringify(next)) {
      memory.current = {instance, plan: next}; setPlan(next)
    }
    setFacts(current => current?.dock.revision === dock.revision && current.technology.revision === technology.revision
      && current.catalog === catalog ? current : {dock, technology, catalog})
  }, [dock, technology, catalog, instance, key])
  const candidates = useMemo(() => facts ? automaticCandidates(facts.dock.ships, facts.catalog, facts.technology.ships) : [], [facts])
  const technologyRows = useMemo(() => new Map(facts ? catalogRows(facts.catalog, facts.technology.ships).map(row => [row.group_type, row]) : []), [facts])
  const candidateIds = useMemo(() => candidates.map(card => card.id), [candidates])
  const included = useMemo(() => new Set(candidates.filter(card => card.group_type != null && !plan?.excluded_groups.includes(card.group_type)).map(card => card.id)), [candidates, plan?.excluded_groups])
  useEffect(() => {
    if (!facts || facts.dock.instance !== instance || !plan) return
    memory.current = {instance, plan}
    try {localStorage.setItem(key, JSON.stringify(plan))} catch { /* localStorage 被禁时计划只留在内存，本次会话仍然可用。 */ }
  }, [facts, plan, instance, key])
  const dockRevision = facts?.dock.revision ?? ''
  const calculationKey = JSON.stringify([instance, dockRevision, facts?.technology.revision, candidateIds])
  const loadPlan = useCallback(() => api.request('mind.plan', {
    instance, revision: dockRevision, ship_ids: candidateIds, target_level: 120,
  }), [instance, dockRevision, candidateIds])
  const planRead = usePageRead(calculationKey,
    connection === 'ready' && facts?.dock.instance === instance && dockRevision === dock?.revision, loadPlan)
  const [lastResult, setLastResult] = useState<{instance: string; value: CultivationReport}>()
  useEffect(() => {
    if (connection !== 'ready') setLastResult(undefined)
    else if (planRead.data) setLastResult({instance, value: planRead.data})
  }, [instance, connection, planRead.data])
  const result = planRead.data ?? (connection === 'ready' && lastResult?.instance === instance ? lastResult.value : undefined)
  const {busy: calculating, error} = planRead
  const conflict = useRef<string | undefined>(undefined)
  useEffect(() => {
    const failure = planRead.errorCause
    if (!(failure instanceof ApiError) || failure.code !== 'CONFLICT' || conflict.current === calculationKey) return
    conflict.current = calculationKey
    refreshDock.current?.()
    refreshTechnology.current()
  }, [calculationKey, planRead.errorCause])
  const estimates = useMemo(() => new Map(result?.ships.map(row => [row.id, row])), [result])
  const totals = useMemo(() => {
    const selected = result?.ships.filter(row => included.has(row.id)) ?? []
    return {included: selected.length, unknown: selected.filter(row => row.status === 'unknown').length,
      mind: selected.reduce((sum, row) => sum + (row.mind ?? 0), 0),
      gold: selected.reduce((sum, row) => sum + (row.gold ?? 0), 0)}
  }, [result, included])
  const efficiencies = useMemo(() => {
    const mindCosts = result?.mind_costs_100_to_120 ?? {}
    return new Map(candidates.map(card => [card.id, technologyEfficiency(card.group_type == null ? undefined : technologyRows.get(card.group_type), mindCosts)]))
  }, [candidates, technologyRows, result?.mind_costs_100_to_120])
  const rows = useMemo(() => {
    const collator = new Intl.Collator(localeForLanguage(language), {numeric: true})
    const valueFor = (card: DockReport['ships'][number]): string | number | null => {
      switch (sort.column) {
        case 'name': return card.name
        case 'level': return card.level || null
        case 'mind': return estimates.get(card.id)?.mind ?? null
        case 'gold': return estimates.get(card.id)?.gold ?? null
        case 'efficiency': return efficiencies.get(card.id)?.value ?? null
      }
    }
    return candidates.filter(card => {
      const technology = card.group_type == null ? undefined : technologyRows.get(card.group_type)
      const search = query.trim()
      return technology && matches(technology, filters, '')
        && (!search || card.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()) || matches(technology, {}, search))
        && (!includedOnly || included.has(card.id))
    }).sort((a, b) => {
      const left = valueFor(a), right = valueFor(b)
      if (left === null && right !== null) return 1
      if (right === null && left !== null) return -1
      const difference = typeof left === 'number' && typeof right === 'number' ? left - right
        : typeof left === 'string' && typeof right === 'string' ? collator.compare(left, right) : 0
      return difference * (sort.direction === 'ascending' ? 1 : -1) || collator.compare(a.name, b.name) || a.id - b.id
    })
  }, [candidates, query, includedOnly, included, sort, estimates, efficiencies, language, filters, technologyRows])
  function sortBy(column: Column) {
    setSort(current => ({column, direction: current.column === column
      ? current.direction === 'ascending' ? 'descending' : 'ascending'
      : column === 'name' ? 'ascending' : 'descending'}))
  }
  function exclude(group: number, excluded: boolean) {
    setPlan(current => current && ({...current, excluded_groups: excluded
      ? [...new Set([...current.excluded_groups, group])] : current.excluded_groups.filter(value => value !== group)}))
  }
  const allSelected = rows.length > 0 && rows.every(card => included.has(card.id))
  function selectFiltered(selected: boolean) {
    const groups = new Set((selected ? rows : candidates).map(card => card.group_type).filter((group): group is number => group !== undefined))
    setPlan(current => current && ({...current, excluded_groups: selected
      ? current.excluded_groups.filter(group => !groups.has(group))
      : [...new Set([...current.excluded_groups, ...groups])]}))
  }
  function group(key: string, options: [string, string][], label = tr(key === 'type' ? 'category' : key)) {
    return <FleetFilterRow filter={key} label={label} options={options} filters={filters} setFilters={setFilters} all={tr('all')}/>
  }
  function toggleExtra() {
    setExtra(!extra)
    if (extra) setFilters(current => {
      const next = {...current}
      for (const key of ['getBonusType', 'getAttr', 'levelBonusType', 'levelAttr']) delete next[key]
      return next
    })
  }
  const review = facts?.dock.ships.filter(card => card.review || !card.group_type).length ?? 0
  function retry() {
    if (!catalog || catalogError) catalogRead.reload()
    technologyRead.reload(); planRead.reload(); refreshDock.current?.()
  }
  if (!facts || facts.dock.instance !== instance || !plan || !result) return <LoadBoundary ready={false} error={reportError || catalogError || technologyError || error} retry={retry}/>
  return <div className="fleet-technology cultivation-calculator">
    {reportError && <ErrorBox message={reportError} retry={onRefresh}/>}
    {catalogError && <ErrorBox message={catalogError} retry={retry}/>}
    {technologyError && <ErrorBox message={technologyError} retry={retry}/>}
    {error && <ErrorBox message={error} retry={retry}/>}
    <section className="ft-summary" aria-busy={calculating}>
      <div className="cultivation-heading"><h2>{ui('mind.title')}</h2><span role="status">{calculating ? ui('mind.calculating') : ''}</span></div>
      <div className="cultivation-totals">
        <div>{ui('mind.units')}<strong>{amount(totals.mind)}</strong></div><div>{ui('mind.gold')}<strong>{amount(totals.gold)}</strong></div>
      </div><p role="status">{ui('mind.includedCount', {count: totals.included - totals.unknown})}{totals.unknown > 0 && ui('mind.unknownCount', {count: totals.unknown})}{candidates.length > included.size && ui('mind.excludedCount', {count: candidates.length - included.size})}</p>
      <small>{ui('mind.autoHint')}</small>
      {review > 0 && <p className="cultivation-review">{ui('mind.reviewCount', {count: review})}<Link to="?tab=data">{ui('mind.reviewLink')}</Link></p>}
    </section>
    <section className="ft-filters" aria-label={ui('mind.filters')}>
      {group('type', [['front', tr('front')], ['back', tr('back')], ...types.map(value => [String(value), tr(`type.${value}`)] as [string, string])])}
      {group('rarity', rarities.map(value => [value, tr(`rarity.${value}`)]))}
      {group('nation', [...new Set([...technologyRows.values()].filter(row => row.technology).map(row => row.nationality))].sort((a, b) => nationOrder(a) - nationOrder(b) || a - b).map(value => [String(value), tr(`nation.${value}`)]))}
      {group('bonusType', types.map(value => [String(value), tr(`type.${value}`)]))}
      {group('attr', attrs.map(value => [String(value), tr(`attr.${value}`)]))}
      {extra && <>{group('getBonusType', types.map(value => [String(value), tr(`type.${value}`)]), `${tr('unlock')} · ${tr('shipClass')}`)}{group('getAttr', attrs.map(value => [String(value), tr(`attr.${value}`)]), `${tr('unlock')} · ${tr('attr')}`)}{group('levelBonusType', types.map(value => [String(value), tr(`type.${value}`)]), `${tr('completionBonus')} · ${tr('shipClass')}`)}{group('levelAttr', attrs.map(value => [String(value), tr(`attr.${value}`)]), `${tr('completionBonus')} · ${tr('attr')}`)}</>}
      {group('status', ['notTrained120', 'missingStar', 'awakening_pending'].map(key => [key, tr(key)]))}
      <div className="ft-filter-row"><strong>{ui('mind.filterFunctions')}</strong><div className="ft-chips"><Button type="button" size="sm" variant={extra ? 'default' : 'outline'} aria-expanded={extra} onClick={toggleExtra}>{tr('extra')}</Button></div></div>
    </section>
    <p className="ft-edit-hint">{ui('mind.costHint')}</p>
    <p className="ft-edit-hint">{ui('mind.efficiencyHint')}</p>
    <div className="ft-search"><Input type="search" aria-label={ui('mind.search')} placeholder={ui('mind.searchPlaceholder')} value={query} onChange={event => setQuery(event.target.value)}/><span title={ui('mind.detailHint')}>{ui('mind.shownCount', {shown: rows.length, total: candidates.length})}</span>
      <span className="flex items-center gap-3"><CheckboxControl id="mind-included-only" checked={includedOnly} onCheckedChange={next => setIncludedOnly(next === true)}/><Label htmlFor="mind-included-only">{ui('mind.includedOnly')}</Label></span>
    </div>
    <div className="ft-table-wrap cultivation-table"><Table scrollLabel={ui('analysis.mind')} className="min-w-[900px] whitespace-nowrap"><TableHeader className="sticky top-0 z-10"><TableRow><TableHead scope="col"><label className="flex items-center gap-2"><CheckboxControl aria-label={ui('mind.selectAll')} checked={allSelected} disabled={!rows.length} onCheckedChange={next => selectFiltered(next === true)}/> {ui('mind.participating')}</label></TableHead>{(Object.entries(columns) as [Column, typeof columns[Column]][]).map(([column, label]) => <TableHead key={column} scope="col" aria-sort={sort.column === column ? sort.direction : 'none'} title={column === 'efficiency' ? ui('mind.efficiencyHint') : undefined}><Button type="button" variant="ghost" size="sm" onClick={() => sortBy(column)}>{ui(`mind.${label}`)}<span aria-hidden="true">{sort.column === column ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></Button></TableHead>)}<TableHead scope="col">{tr('awakening_pending')}</TableHead></TableRow></TableHeader><TableBody>
      {rows.map(card => {
        const groupType = card.group_type
        const row = estimates.get(card.id), participating = included.has(card.id), efficiency = efficiencies.get(card.id), awakeningPending = groupType != null && technologyRows.get(groupType)?.awakening_pending === true
        return <TableRow key={card.id} className={participating ? '' : 'cultivation-excluded'}>
          <TableCell>{groupType != null && <CheckboxControl aria-label={ui('mind.participatingShip', {name: card.name})} checked={participating} onCheckedChange={next => exclude(groupType, !next)}/>}</TableCell>
          <TableCell className="ft-name"><Link to={`?tab=data&ship=${card.id}`}>{card.name}</Link>{participating && row?.status === 'unknown' && <small className="cultivation-warning">{ui('mind.unknownCost')} · <Link to={`?tab=data&ship=${card.id}`}>{ui('mind.check')}</Link></small>}</TableCell>
          <TableCell className="text-center">{card.level || ui('mind.unknown')}</TableCell><TableCell className="text-right tabular-nums">{amount(row?.mind)}</TableCell><TableCell className="text-right tabular-nums">{amount(row?.gold)}</TableCell>
          <TableCell className="text-right tabular-nums" title={efficiency?.value == null || efficiency.points == null ? undefined : ui('mind.efficiencyDetail', {points: efficiency.points, mind: amount(efficiency.mind)})}>{efficiency?.value == null ? '—' : efficiency.value.toLocaleString(localeForLanguage(language), {minimumFractionDigits: 2, maximumFractionDigits: 2})}</TableCell>
          <TableCell className={`text-center ${awakeningPending ? 'ft-awakening-pending' : ''}`} title={ui('mind.awakeningHint')}><span className="ft-mark" aria-label={`${card.name} · ${tr('awakening_pending')} · ${tr(awakeningPending ? 'marked' : 'notMarked')}`}>{awakeningPending ? '✓' : '—'}</span></TableCell>
        </TableRow>
      })}
    </TableBody></Table></div>
    {!rows.length && <p>{ui(candidates.length ? 'mind.noMatches' : 'mind.noCandidates')}</p>}
  </div>
}
