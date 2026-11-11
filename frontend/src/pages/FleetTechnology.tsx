import {FleetFilterRow, fleetShipTypes as types, fleetAttributes as attrs, fleetRarities as rarities} from '../fleet-tech/filters'
import {useEffect, useMemo, useRef, useState} from 'react'
import {Link, useParams, useSearchParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, Loading, PageTitle} from '../components/ui'
import {Select} from '../components/FormControls'
import {Input} from '../components/ui/input'
import {fleetFactionOrder, translateFleetTech} from '../fleet-tech/i18n'
import {useFleetPreference} from '../fleet-tech/preferences'
import {catalogRows, changeMilestone, complete, matches, milestones, recordFields, shipType, type Bonuses, type Catalog, type Change, type Milestone, type RecordField, type Report, type Row, type State} from '../fleet-tech/types'
import {technologyEfficiency} from '../mind/cultivation'
import '../fleet-tech/style.css'

const stageLabel = {owned: 'get', full_star: 'star', lv120: 'Lv.120'}
const stateKey = (value: State) => value ? 'finished' : 'notFinished'
const stateSymbol = (value: State) => value ? '✓' : '—'
const nextState = (value: State): State => !value
const nameFor = (row: Row, language: string) => row.names[language === 'en-US' ? 'en' : language === 'ja-JP' ? 'jp' : language === 'zh-TW' ? 'tw' : 'cn'] || row.name
const pointsFor = (row: Row, key: Milestone) => row.technology?.[key === 'owned' ? 'pt_get' : key === 'full_star' ? 'pt_upgrage' : 'pt_level'] ?? 0
const maximumPoints = (row: Row) => milestones.reduce((sum, key) => sum + pointsFor(row, key), 0)
const nationOrder = (value: number) => {const index = fleetFactionOrder.indexOf(value); return index < 0 ? fleetFactionOrder.length : index}
const columns = ['code', 'name', 'nation', 'shipClass', 'get', 'star', 'Lv.120', 'total', 'unlock', 'completionBonus', 'efficiency', 'awakening_pending'] as const
type Column = typeof columns[number]
type Sort = {column: Column; direction: 'ascending' | 'descending'}
type Draft = {revision: string; changes: Record<number, Change>; nations: Record<string, number | null>}

function effectFor(row: Row, stage: 'get' | 'level', tr: (key: string) => string) {
  const t = row.technology
  if (!t) return '—'
  return `${[...new Set(t[`add_${stage}_shiptype`].map(shipType))].map(type => tr(`type.${type}`)).join('/')} ${tr(`attr.${t[`add_${stage}_attr`]}`)}+${t[`add_${stage}_value`]}`
}

export function TechnologyTable({rows, language, tr, mindCosts = {}, editing = false, disabled = false, sort = {column: 'code', direction: 'ascending'}, onSort, onChange, modified = [], targetGroup}: {
  rows: Row[]; language: string; tr: (key: string) => string; editing?: boolean; disabled?: boolean; sort?: Sort
  mindCosts?: Record<string, number>
  onSort?: (column: Column) => void; onChange?: (row: Row, key: RecordField, value: State) => void; modified?: number[]; targetGroup?: string | null
}) {
  function header(column: Column, rowSpan = 1) {
    return <th key={column} scope="col" rowSpan={rowSpan} aria-sort={sort.column === column ? sort.direction : 'none'} title={column === 'efficiency' ? tr('efficiencyHint') : undefined}><button type="button" className="ft-sort" onClick={() => onSort?.(column)}>{tr(column)}<span aria-hidden="true">{sort.column === column ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></button></th>
  }
  return <div className="ft-table-wrap"><table><thead><tr>{columns.slice(0, 4).map(column => header(column, 2))}<th scope="colgroup" colSpan={4}>{tr('points')}</th><th scope="colgroup" colSpan={2}>{tr('statBonuses')}</th>{header('efficiency', 2)}{header('awakening_pending', 2)}</tr><tr>{columns.slice(4, 10).map(column => header(column))}</tr></thead><tbody>{rows.map(row => {
    const title = `${tr('held')}: ${row.current_count} · ${row.current_level === null ? tr('unknown') : `Lv.${row.current_level}`}`
    const identityHighlight = row.lv120 ? 'ft-marked' : ''
    const efficiency = technologyEfficiency(row, mindCosts)
    return <tr key={row.group_type} id={`technology-${row.group_type}`} data-group={row.group_type} className={[complete(row) ? 'ft-complete' : '', modified.includes(row.group_type) ? 'ft-modified' : '', targetGroup === String(row.group_type) ? 'ft-target' : ''].filter(Boolean).join(' ')}>
      <td className={identityHighlight}>{String(row.code).padStart(3, '0')}</td><td className={`ft-name ft-rarity-${row.rarity} ${identityHighlight}`}><Link to={`?tab=data&group=${row.group_type}`} title={title}>{nameFor(row, language)}</Link></td><td className={identityHighlight}>{tr(`nation.${row.nationality}`)}</td><td className={identityHighlight}>{tr(`type.${shipType(row.type)}`)}</td>
      {milestones.map(key => <td key={key} className={`ft-point ft-state-${stateKey(row[key])}`}><button type="button" className="ft-milestone-button" disabled={!editing || disabled} aria-pressed={row[key]} aria-label={`${row.name} · ${tr(stageLabel[key])} · ${tr(stateKey(row[key]))}`} title={editing ? tr('toggleMilestone') : tr(stateKey(row[key]))} onClick={() => onChange?.(row, key, nextState(row[key]))}><span className="ft-point-value"><b>{pointsFor(row, key)}</b><span className="ft-mark" aria-hidden="true">{stateSymbol(row[key])}</span></span></button></td>)}
      <td className={complete(row) ? 'ft-marked' : ''} title={`${tr('confirmed')}: ${row.points}`}>{maximumPoints(row)}</td>
      {(['get', 'level'] as const).map(stage => {
        const key = stage === 'get' ? 'owned' : 'lv120', label = `${row.name} · ${tr(stage === 'get' ? 'unlock' : 'completionBonus')} · ${tr(stateKey(row[key]))}`
        return <td key={stage} className={`ft-unlock ${row[key] === true ? 'ft-marked' : ''}`}><button type="button" className="ft-milestone-button" disabled={!editing || disabled} aria-pressed={row[key]} aria-label={label} title={editing ? tr('toggleMilestone') : tr(stateKey(row[key]))} onClick={() => onChange?.(row, key, nextState(row[key]))}><span>{effectFor(row, stage, tr)}</span><span className="ft-mark" aria-hidden="true">{stateSymbol(row[key])}</span></button></td>
      })}
      <td title={efficiency.value == null ? undefined : `${efficiency.points} ÷ ${efficiency.mind?.toLocaleString(language)} × 1000（100→120）`}>{efficiency.value == null ? '—' : efficiency.value.toLocaleString(language, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
      <td className={`ft-flag ${row.awakening_pending ? 'ft-awakening-pending' : ''}`}><button type="button" className="ft-milestone-button" disabled={!editing || disabled} aria-pressed={row.awakening_pending} aria-label={`${row.name} · ${tr('awakening_pending')} · ${tr(row.awakening_pending ? 'marked' : 'notMarked')}`} title={tr('awakeningHint')} onClick={() => onChange?.(row, 'awakening_pending', !row.awakening_pending)}><span className="ft-mark" aria-hidden="true">{stateSymbol(row.awakening_pending)}</span></button></td>
    </tr>
  })}</tbody></table></div>
}

export function FleetTechnology() {
  const [search] = useSearchParams(), targetGroup = search.get('group')
  const {instance = ''} = useParams(), {language, ui, notify} = useApp(), connection = useConnection()
  const tr = (key: string) => key === 'Lv.120' ? key : translateFleetTech(language, key)
  const [catalog, setCatalog] = useState<Catalog>(), [report, setReport] = useState<Report>()
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [query, setQuery] = useFleetPreference<string>(instance, 'technology.query', ''), [filters, setFilters] = useFleetPreference<Record<string, string[]>>(instance, 'technology.filters', {})
  const [sort, setSort] = useFleetPreference<Sort>(instance, 'technology.sort', {column: 'code', direction: 'ascending'})
  const [editing, setEditing] = useFleetPreference<boolean>(instance, 'technology.editing', false), [bonuses, setBonuses] = useFleetPreference<boolean>(instance, 'technology.bonuses', false), [extra, setExtra] = useFleetPreference<boolean>(instance, 'technology.extra', false)
  const scope = useRef(0), writing = useRef(false)
  const storageKey = `azurpilot.fleet-tech.v1.${instance}`
  const [draft, setDraft] = useState<Draft | null>(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')
      if (!value || typeof value.revision !== 'string' || !value.changes || !value.nations) return null
      for (const change of Object.values(value.changes) as Record<string, unknown>[]) {
        for (const key of recordFields) if (key in change) change[key] = change[key] === true
        if (change.owned === false) {change.full_star = false; change.lv120 = false}
      }
      return value
    } catch {return null}
  })
  const dirty = !!draft && (!!Object.keys(draft.changes).length || !!Object.keys(draft.nations).length)
  const stale = dirty && !!report && draft.revision !== report.revision
  useEffect(() => {
    try {if (dirty) sessionStorage.setItem(storageKey, JSON.stringify(draft)); else sessionStorage.removeItem(storageKey)} catch { /* Optional browser draft. */ }
  }, [draft, dirty, storageKey])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {if (dirty) {event.preventDefault(); event.returnValue = ''}}
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  const rows = useMemo(() => catalog ? catalogRows(catalog, report?.ships ?? []).filter(row => row.technology) : [], [catalog, report])
  const previewRows = useMemo(() => rows.map(row => {
    const next = {...row, ...draft?.changes[row.group_type]}
    return {...next, points: milestones.reduce((sum, key) => sum + (next[key] === true ? pointsFor(next, key) : 0), 0)}
  }), [rows, draft])
  const levels = {...report?.nation_levels, ...draft?.nations}
  const totals = useMemo(() => {
    const shipBonuses: Bonuses = {}, nationBonuses: Bonuses = {}, bonuses: Bonuses = {}
    const add = (target: Bonuses, types: number[], attr: number, amount: number) => {
      for (const type of new Set(types.map(shipType))) {const values = target[String(type)] ??= {}; values[String(attr)] = (values[String(attr)] ?? 0) + amount}
    }
    for (const row of previewRows) {
      const t = row.technology!
      for (const stage of ['get', 'level'] as const) if (row[stage === 'get' ? 'owned' : 'lv120'] === true) {
        add(shipBonuses, t[`add_${stage}_shiptype`], t[`add_${stage}_attr`], t[`add_${stage}_value`])
        add(bonuses, t[`add_${stage}_shiptype`], t[`add_${stage}_attr`], t[`add_${stage}_value`])
      }
    }
    for (const [id, level] of Object.entries({...report?.nation_levels, ...draft?.nations})) if (level && catalog?.nations[id]?.[level - 1]) {
      for (const [types, attr, amount] of catalog.nations[id]![level - 1]!) {add(nationBonuses, types, attr, amount); add(bonuses, types, attr, amount)}
    }
    return {shipBonuses, nationBonuses, bonuses, points: previewRows.reduce((sum, row) => sum + row.points, 0), counts: Object.fromEntries(milestones.map(key => [key, previewRows.filter(row => row[key] === true).length]))}
  }, [previewRows, report?.nation_levels, draft?.nations, catalog])
  const filtered = useMemo(() => {
    const collator = new Intl.Collator(language, {numeric: true}), previews = new Map(previewRows.map(row => [row.group_type, row]))
    const valueFor = (row: Row): string | number | null => {
      const t = row.technology!
      switch (sort.column) {
        case 'code': return row.code
        case 'name': return nameFor(row, language)
        case 'nation': return nationOrder(row.nationality)
        case 'shipClass': return types.indexOf(shipType(row.type))
        case 'get': return t.pt_get
        case 'star': return t.pt_upgrage
        case 'Lv.120': return t.pt_level
        case 'total': return maximumPoints(row)
        case 'unlock': return effectFor(row, 'get', tr)
        case 'completionBonus': return effectFor(row, 'level', tr)
        case 'awakening_pending': return Number(row.awakening_pending)
        case 'efficiency': return technologyEfficiency(row, catalog?.mind_costs_100_to_120 ?? {}).value
      }
    }
    // Keep edited rows visible until save, even if a status filter no longer matches the draft.
    return rows.filter(row => matches(row, filters, query)).sort((a, b) => {
      const left = valueFor(a), right = valueFor(b)
      if (left === null && right !== null) return 1
      if (right === null && left !== null) return -1
      const result = typeof left === 'number' && typeof right === 'number' ? left - right : collator.compare(String(left), String(right))
      return result * (sort.direction === 'ascending' ? 1 : -1) || a.code - b.code || a.group_type - b.group_type
    }).map(row => previews.get(row.group_type)!)
  }, [rows, previewRows, filters, query, sort, language, catalog?.mind_costs_100_to_120])
  useEffect(() => {
    if (targetGroup && report && catalog) document.getElementById(`technology-${targetGroup}`)?.scrollIntoView?.({block: 'center'})
  }, [targetGroup, report, catalog])
  async function reload(includeCatalog = false) {
    const token = scope.current
    try {
      const [data, value] = await Promise.all([includeCatalog ? api.request('fleetTech.catalog', {instance}) : Promise.resolve(undefined), api.request('fleetTech.report', {instance})])
      if (scope.current === token) {if (data) setCatalog(data); setReport(value); setError('')}
    } catch (e) {if (scope.current === token) setError((e as Error).message)}
  }
  useEffect(() => {
    scope.current++; setCatalog(undefined); setReport(undefined); setError(''); setBusy(false); writing.current = false
    if (connection === 'ready') void reload(true)
    return () => {scope.current++}
  }, [instance, connection])
  function change(row: Row, key: RecordField, value: State) {
    if (!report || busy || connection !== 'ready') return
    setDraft(current => {
      const changes = {...current?.changes}, original = rows.find(value => value.group_type === row.group_type)!
      const state = {group_type: row.group_type, owned: original.owned, full_star: original.full_star, lv120: original.lv120, awakening_pending: original.awakening_pending, ...current?.changes[row.group_type]}
      const next = key === 'awakening_pending' ? {...state, awakening_pending: value} : changeMilestone(state, key, value, row.full_star_rule)
      // Keep all milestone states together, but a flag-only draft must stay independent.
      const pending: Change = {group_type: row.group_type}
      if (milestones.some(field => next[field] !== original[field])) {
        for (const field of milestones) pending[field] = next[field]
      }
      if (next.awakening_pending !== original.awakening_pending) pending.awakening_pending = next.awakening_pending
      if (Object.keys(pending).length === 1) delete changes[row.group_type]; else changes[row.group_type] = pending
      const nations = current?.nations ?? {}
      return Object.keys(changes).length || Object.keys(nations).length ? {revision: current?.revision ?? report.revision, changes, nations} : null
    })
  }
  function changeNation(id: string, value: number | null) {
    if (!report) return
    setDraft(current => {
      const nations = {...current?.nations}, changes = current?.changes ?? {}
      if (value === (report.nation_levels[id] ?? null)) delete nations[id]; else nations[id] = value
      return Object.keys(changes).length || Object.keys(nations).length ? {revision: current?.revision ?? report.revision, changes, nations} : null
    })
  }
  async function save() {
    if (!report || !draft || !dirty || stale || writing.current) return
    const token = scope.current
    writing.current = true; setBusy(true); setError('')
    try {
      const changes = Object.values(draft.changes).map(change => {
        const original = rows.find(row => row.group_type === change.group_type)!
        // A manual flag must not resubmit or normalize unrelated milestone states.
        const final = {...original, ...change}
        return {group_type: change.group_type,
          ...(milestones.some(key => final[key] !== original[key]) ? {owned: final.owned, full_star: final.full_star, lv120: final.lv120} : {}),
          ...(final.awakening_pending !== original.awakening_pending ? {awakening_pending: final.awakening_pending} : {}),
        }
      })
      const value = await api.request('fleetTech.patch', {instance, revision: draft.revision, changes, nations: draft.nations})
      if (token === scope.current) {setReport(value); setDraft(null); notify(tr('saved'))}
    } catch (e) {if (token === scope.current) setError((e as Error).message)}
    finally {if (token === scope.current) {writing.current = false; setBusy(false)}}
  }
  async function mergeShips() {
    if (!report || dirty || writing.current) return
    const token = scope.current
    writing.current = true; setBusy(true); setError('')
    try {
      const value = await api.request('fleetTech.mergeShips', {instance, revision: report.revision})
      if (token === scope.current) {setReport(value); notify(tr('mergeSaved'))}
    } catch (e) {if (token === scope.current) setError((e as Error).message)}
    finally {if (token === scope.current) {writing.current = false; setBusy(false)}}
  }
  function group(key: string, options: [string, string][], label = tr(key === 'type' ? 'category' : key)) {
    return <FleetFilterRow filter={key} label={label} options={options} filters={filters} setFilters={setFilters} all={tr('all')}/>
  }
  function bonusList(values: Bonuses) {return <div className="ft-bonus-grid">{types.filter(type => values[String(type)] && Object.keys(values[String(type)]!).length).map(type => <div key={type}><b>{tr(`type.${type}`)}</b> {attrs.filter(attr => values[String(type)]![String(attr)]).map(attr => `${tr(`attr.${attr}`)}+${values[String(type)]![String(attr)]}`).join(' · ')}</div>)}</div>}
  if (!catalog || !report) return error ? <ErrorBox message={error} retry={() => void reload(!catalog)}/> : <Loading/>
  const disabled = busy || connection !== 'ready'
  return <div className="fleet-technology">
    <PageTitle title={tr('title')} actions={<button className="button secondary" disabled={disabled} onClick={() => void reload()}>{ui('mind.reload')}</button>}/>
    {error && <ErrorBox message={error}/>}
    <section className="ft-summary"><div><p>{tr('max')}：<b>{catalog.max_points.toLocaleString()}</b> · {tr('confirmed')}：<b>{totals.points.toLocaleString()}</b>{dirty && <span className="ft-draft-label">{tr('draftPreview')}</span>}</p><p>{tr('four')}：{['1', '2', '3', '4'].map(id => `${tr(`nation.${id}`)} ${catalog.nation_points[id] ?? 0}`).join(' · ')}</p><p>{milestones.map(key => <span key={key}>{tr(stageLabel[key])}：{totals.counts[key]} / {rows.length}　</span>)}</p><small>{tr('independentHint')}</small></div></section>
    <section className="ft-filters">
      {group('type', [['front', tr('front')], ['back', tr('back')], ...types.map(value => [String(value), tr(`type.${value}`)] as [string, string])])}
      {group('rarity', rarities.map(value => [value, tr(`rarity.${value}`)]))}
      {group('nation', [...new Set(rows.map(row => row.nationality))].sort((a, b) => nationOrder(a) - nationOrder(b) || a - b).map(value => [String(value), tr(`nation.${value}`)]))}
      {group('bonusType', types.map(value => [String(value), tr(`type.${value}`)]))}
      {group('attr', attrs.map(value => [String(value), tr(`attr.${value}`)]))}
      {extra && <>{group('getBonusType', types.map(value => [String(value), tr(`type.${value}`)]), `${tr('unlock')} · ${tr('shipClass')}`)}{group('getAttr', attrs.map(value => [String(value), tr(`attr.${value}`)]), `${tr('unlock')} · ${tr('attr')}`)}{group('levelBonusType', types.map(value => [String(value), tr(`type.${value}`)]), `${tr('completionBonus')} · ${tr('shipClass')}`)}{group('levelAttr', attrs.map(value => [String(value), tr(`attr.${value}`)]), `${tr('completionBonus')} · ${tr('attr')}`)}</>}
      {group('status', ['incomplete', 'unfinished', 'notTrained120', 'missingStar', 'awakening_pending', 'unowned', 'owned', 'lv120'].map(key => [key, tr(key === 'lv120' ? 'Lv.120' : key)]))}
      <div className="ft-filter-row"><strong>{tr('functions')}</strong><div className="ft-chips"><button aria-pressed={editing} onClick={() => setEditing(!editing)}>{tr('edit')}</button><button aria-expanded={bonuses} aria-controls="fleet-tech-bonuses" onClick={() => setBonuses(!bonuses)}>{tr('bonuses')}</button><button aria-expanded={extra} onClick={() => {setExtra(!extra); if (extra) setFilters(current => {const next = {...current}; for (const key of ['getBonusType', 'getAttr', 'levelBonusType', 'levelAttr']) delete next[key]; return next})}}>{tr('extra')}</button></div></div>
    </section>
    <div className="ft-toolbar ft-savebar"><button className="button primary" disabled={disabled || !dirty || stale} onClick={() => void save()}>{ui('analysis.save')}</button>{dirty && <><span role="status">{tr('pendingEdits')}: {Object.keys(draft.changes).length + Object.keys(draft.nations).length}</span><button className="button secondary" disabled={busy} onClick={() => {setDraft(null); setError('')}}>{ui('analysis.discard')}</button></>}<button className="button secondary" disabled={disabled || dirty} title={dirty ? tr('saveBeforeMerge') : tr('mergeHint')} onClick={() => void mergeShips()}>{tr('mergeShips')}</button><small>{tr('mergeHint')}</small></div>
    {stale && <p role="alert">{ui('analysis.stale')}</p>}
    {bonuses && <section id="fleet-tech-bonuses" className="ft-bonuses"><h2>{tr('bonuses')}{dirty && ` · ${tr('draftPreview')}`}</h2><div className="ft-nation-levels">{Object.entries(catalog.nations).map(([id, values]) => <label key={id}>{tr(`nation.${id}`)} {tr('factionLevel')}<Select aria-label={`${tr(`nation.${id}`)} ${tr('factionLevel')}`} disabled={disabled} value={levels[id] ?? ''} onChange={event => changeNation(id, event.target.value === '' ? null : Number(event.target.value))}><option value="">{tr('unspecified')}</option>{Array.from({length: values.length + 1}, (_, value) => <option key={value} value={value}>{value}</option>)}</Select></label>)}</div><h3>{tr('shipBonuses')}</h3>{bonusList(totals.shipBonuses)}<h3>{tr('nationBonuses')}</h3>{bonusList(totals.nationBonuses)}<h3>{tr('total')}</h3>{bonusList(totals.bonuses)}<p>{tr('unknownImpact')}</p></section>}
    <div className="ft-search"><Input aria-label={tr('search')} placeholder={tr('search')} value={query} onChange={event => setQuery(event.target.value)}/><span>{ui('mind.rowCount', {count: filtered.length})}</span><span className="ft-state-legend">✓ {tr('finished')} · — {tr('notFinished')}</span></div>
    {editing && <p className="ft-edit-hint">{tr('inlineEditHint')}</p>}
    <TechnologyTable rows={filtered} language={language} tr={tr} mindCosts={catalog.mind_costs_100_to_120} editing={editing} disabled={disabled} sort={sort} onSort={column => setSort(current => ({column, direction: current.column === column ? current.direction === 'ascending' ? 'descending' : 'ascending' : column === 'efficiency' ? 'descending' : 'ascending'}))} onChange={change} modified={Object.keys(draft?.changes ?? {}).map(Number)} targetGroup={targetGroup}/>
    {!filtered.length && <p>{ui('mind.empty')}</p>}
    <footer><small>{tr('version')}：{catalog.updated_at}</small><a href="https://wiki.biligame.com/blhx/舰队科技#舰队科技列表" target="_blank" rel="noreferrer">{tr('attribution')}</a></footer>
  </div>
}
