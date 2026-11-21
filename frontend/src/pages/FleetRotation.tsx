/**
 * @fileoverview 舰队轮换（联动换船）规则编辑页：直接写 FleetInfo.FleetRotation 配置，并轮询展示后台换船进度。
 */

import {LoadBoundary} from '../components/ui/load-boundary'


import {Button} from '../components/ui/button'
import {useCallback, useEffect, useRef, useState} from 'react'
import {usePageRead} from '../app/usePageRead'
import {Panel, PanelHeading} from '../components/ui/page'
import {Link, useParams} from 'react-router-dom'
import {api} from '../api/client'
import type {Config} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {editor} from '../config/editors'
import {expectConfig, isConfigConflict} from '../config/expectConfig'
import {Checkbox} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {PageTitle} from '../components/ui'

type Rule = {slots: number[]; sources: number[]; favourite?: boolean}
type Rules = Record<string, Rule>
type Progress = Record<string, {last_source?: number; source?: number; favourite?: boolean; done?: number[]; pending?: unknown; rescan?: boolean}>
/** 舰队与舰位共用的编号范围 1–6。 */
const numbers = [1, 2, 3, 4, 5, 6] as const
const rotationProgress = (value: unknown): Progress => value && typeof value === 'object' && !Array.isArray(value) ? value as Progress : {}

/** 把任意存储值解析成六支舰队的联动规则表：缺失字段补空档，结构不合法（非对象或数组）时抛错。 */
export function rotationRules(value: unknown): Rules {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value ?? {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Invalid fleet rules')
  const records = parsed as Record<string, unknown>
  return Object.fromEntries(numbers.map(number => {
    const rule = records[String(number)]
    const fields = rule && typeof rule === 'object' && !Array.isArray(rule) ? rule as Record<string, unknown> : {}
    return [String(number), {slots: Array.isArray(fields.slots) ? fields.slots : [], sources: Array.isArray(fields.sources) ? fields.sources : [], favourite: fields.favourite === true}]
  }))
}

/** 仅编辑联动规则，不注册调度任务，不启动游戏。 */
export function FleetRotation() {
  const {instance = ''} = useParams()
  const {ui, instances, notify} = useApp(), connection = useConnection()
  const [rules, setRules] = useState<Rules>()
  const [progress, setProgress] = useState<Progress>({})
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)
  const running = instances.find(item => item.name === instance)?.status === 'running'
  const disabled = busy || connection !== 'ready'
  const load = useCallback(async () => {
    const config = await api.request('config.get', {instance})
    // Validate rules in the loader so invalid data reaches the shared error state.
    rotationRules(config.values.FleetInfo?.FleetRotation?.Rules)
    return config
  }, [instance])
  const pollAfter = useCallback(() => running ? 3000 : 0, [running])
  const read = usePageRead(instance, connection === 'ready', load, pollAfter)
  const baseline = useRef<{key: string; value?: Config}>({key: instance})
  if (baseline.current.key !== instance) baseline.current = {key: instance}
  const editing = useRef(false)
  editing.current = dirty || busy
  useEffect(() => {setDirty(false); setConflict(false); setError('')}, [instance])
  useEffect(() => {
    if (!read.data) return
    const values = read.data.values.FleetInfo?.FleetRotation
    if (!editing.current || baseline.current.value === undefined) {
      const next = rotationRules(values?.Rules)
      baseline.current.value = read.data
      setRules(next); setDirty(false)
    }
    setProgress(rotationProgress(values?.State))
  }, [instance, read.data])

  function change(fleet: number, field: 'slots' | 'sources', number: number) {
    setRules(previous => {
      if (!previous) return undefined
      const next = {...previous}, rule = {...(next[String(fleet)] ?? {slots: [], sources: []})}
      rule[field] = rule[field].includes(number) ? rule[field].filter(value => value !== number) : [...rule[field], number].sort()
      next[String(fleet)] = rule
      return next
    })
    setDirty(true)
  }

  async function save(reset = false) {
    if (!rules) return
    setBusy(true); setError('')
    try {
      await editor(`config:${instance}`).settled()
      const result = await api.request('config.patch', {instance, changes: [
        ...expectConfig(baseline.current.value, [
        {path: 'FleetInfo.FleetRotation.Rules', value: JSON.stringify(rules)},
        ]),
        ...(reset ? [{path: 'FleetInfo.FleetRotation.State', value: {}}] : []),
      ]})
      baseline.current.value = result
      setConflict(false)
      read.setData(result)
      setProgress(rotationProgress(result.values.FleetInfo?.FleetRotation?.State))
      setDirty(false); notify(ui('rotation.saved'))
    } catch (error) {if (isConfigConflict(error)) setConflict(true); else setError((error as Error).message)}
    finally {setBusy(false)}
  }

  return <>
    <PageTitle title={ui('rotation.title')} actions={<>
      <Button disabled={disabled || !dirty} onClick={() => void save()}>{ui('rotation.save')}</Button>
    </>}/>
    <p className="muted">{ui('rotation.help')}</p>
    <p className="muted">{ui('rotation.duplicates')}</p>
    <p><Link to={`/i/${instance}/task/FleetSwitch?tab=training`}>{ui('training.title')}</Link></p>
    {conflict && <p role="alert">{ui('edit.conflict')} <Button type="button" variant="outline" onClick={() => {setDirty(false); setConflict(false); read.reload()}}>{ui('edit.reloadDiscard')}</Button></p>}
    <LoadBoundary ready={!!rules && read.ready} error={error || read.error} retry={read.reload}>
    {rules && <div className="fleet-grid">{numbers.map(fleet => <Panel key={fleet} aria-label={ui('fleet.title', {number: fleet})}>
      <PanelHeading title={ui('fleet.title', {number: fleet})}/>
      <div className="fleet-column"><h3>{ui('rotation.slots')}</h3>{numbers.map(slot => <span key={slot} className="flex items-center gap-3"><Checkbox id={`fleet-${fleet}-slot-${slot}`} checked={rules[String(fleet)]?.slots.includes(slot) ?? false} disabled={disabled} onCheckedChange={() => change(fleet, 'slots', slot)}/><Label htmlFor={`fleet-${fleet}-slot-${slot}`}>
        {ui('fleet.slot', {number: slot})} · {ui(rules[String(fleet)]?.slots.includes(slot) ? 'rotation.swap' : 'rotation.keep')}
      </Label></span>)}</div>
      <div className="fleet-column"><h3>{ui('rotation.sources')}</h3><div className="flex flex-wrap gap-2.5">{numbers.filter(number => number !== fleet).map(number => <span key={number} className="flex items-center gap-3"><Checkbox id={`fleet-${fleet}-source-${number}`} aria-label={ui('rotation.source', {number})} checked={rules[String(fleet)]?.sources.includes(number) ?? false} disabled={disabled} onCheckedChange={() => change(fleet, 'sources', number)}/><Label htmlFor={`fleet-${fleet}-source-${number}`}>{number}</Label></span>)}<span className="flex items-center gap-3"><Checkbox id={`fleet-${fleet}-favourite`} checked={rules[String(fleet)]?.favourite ?? false} disabled={disabled} onCheckedChange={next => {
          const favourite = next === true
          setRules(previous => previous ? {...previous, [String(fleet)]: {...(previous[String(fleet)] ?? {slots: [], sources: []}), favourite}} : undefined); setDirty(true)
        }}/><Label htmlFor={`fleet-${fleet}-favourite`}>{ui('rotation.favourite')}</Label></span></div><p className="muted">{ui('rotation.favouriteHelp')}</p></div>
      <div className="fleet-column"><p>{(progress[String(fleet)]?.pending || progress[String(fleet)]?.rescan) && !running ? ui('rotation.uncertain') : progress[String(fleet)]?.source ? ui('rotation.inProgress', {number: progress[String(fleet)]?.source ?? 0}) : progress[String(fleet)]?.favourite ? ui('rotation.lastFavourite') : progress[String(fleet)]?.last_source ? ui('rotation.last', {number: progress[String(fleet)]?.last_source ?? 0}) : ui('rotation.none')}</p></div>
    </Panel>)}</div>}</LoadBoundary>
    <Button variant="outline" disabled={disabled || running || !rules} onClick={() => void save(true)}>{ui('rotation.reset')}</Button>
  </>
}
